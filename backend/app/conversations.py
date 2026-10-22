"""Private conversation library. Session IDs are identifiers, never credentials."""
import re
import unicodedata
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import authenticated
from .localdb import connect, decoded, now
from .v2store import relation

router = APIRouter(tags=['Lịch sử hội thoại'])


def search_query(value):
    normalized = unicodedata.normalize('NFD',value.casefold())
    normalized = ''.join(c for c in normalized if unicodedata.category(c)!='Mn').replace('đ','d')
    tokens = re.findall(r'[^\W_]+',normalized)
    if len(tokens)>12:
        raise HTTPException(422,'Tìm kiếm tối đa 12 từ. Hãy rút gọn từ khóa.')
    # Quoted tokens + our own prefix operator; user text never becomes FTS syntax.
    return ' AND '.join('"'+token+'"*' for token in tokens)


def owned(conn,uid,identifier):
    row = conn.execute('SELECT s.id,s.created_at,c.title,c.updated_at FROM chat_sessions s JOIN conversation_metadata c ON c.session_id=s.id WHERE s.id=? AND s.account_id=?',(str(identifier),uid)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy cuộc trò chuyện.')
    return dict(row)


def search_condition(query):
    if not query.strip():
        return '',[]
    match = search_query(query)
    if not match:
        return ' AND 0',[]
    return ''' AND (c.rowid IN (SELECT rowid FROM conversation_title_search WHERE conversation_title_search MATCH ?)
      OR EXISTS (SELECT 1 FROM messages m WHERE m.session_id=s.id AND m.rowid IN
        (SELECT rowid FROM conversation_message_search WHERE conversation_message_search MATCH ?)))''',[match,match]


@router.get('/conversations')
def list_conversations(q:str=Query(default='',max_length=200),page:int=Query(default=1,ge=1),page_size:int=Query(default=20,ge=1,le=50),account=Depends(authenticated)):
    clause,params = search_condition(q)
    with connect() as conn:
        conn.execute('BEGIN')
        source = ' FROM chat_sessions s JOIN conversation_metadata c ON c.session_id=s.id WHERE s.account_id=?'+clause
        args = [account['id'],*params]
        total = conn.execute('SELECT count(*)'+source,args).fetchone()[0]
        rows = conn.execute('SELECT s.id,s.created_at,c.title,c.updated_at'+source+' ORDER BY c.updated_at DESC,s.id DESC LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size]).fetchall()
        items=[]
        for row in rows:
            item=dict(row)
            item['message_count']=conn.execute('SELECT count(*) FROM messages WHERE session_id=?',(row['id'],)).fetchone()[0]
            preview=conn.execute('SELECT id,content FROM messages WHERE session_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(row['id'],)).fetchone()
            match=search_query(q) if q.strip() else ''
            if match:
                hit=conn.execute('SELECT id,content FROM messages WHERE session_id=? AND rowid IN (SELECT rowid FROM conversation_message_search WHERE conversation_message_search MATCH ?) ORDER BY created_at DESC,rowid DESC LIMIT 1',(row['id'],match)).fetchone()
            else:
                hit=None
            item['matched_message_id']=hit['id'] if hit else None
            item['preview']=(hit or preview)['content'][:240] if (hit or preview) else ''
            items.append(item)
        return {'items':items,'total':total,'page':page,'page_size':page_size}


@router.get('/conversations/bookmarks')
def list_bookmarks(q:str=Query(default='',max_length=200),page:int=Query(default=1,ge=1),page_size:int=Query(default=20,ge=1,le=50),account=Depends(authenticated)):
    source=' FROM conversation_bookmarks b JOIN messages m ON m.id=b.message_id JOIN chat_sessions s ON s.id=m.session_id JOIN conversation_metadata c ON c.session_id=s.id WHERE b.account_id=? AND s.account_id=?'
    args=[account['id'],account['id']]
    if q.strip():
        match=search_query(q)
        if match:
            source+=' AND (m.rowid IN (SELECT rowid FROM conversation_message_search WHERE conversation_message_search MATCH ?) OR c.rowid IN (SELECT rowid FROM conversation_title_search WHERE conversation_title_search MATCH ?))'
            args += [match,match]
        else:
            source+=' AND 0'
    with connect() as conn:
        conn.execute('BEGIN')
        total=conn.execute('SELECT count(*)'+source,args).fetchone()[0]
        items=[dict(row) for row in conn.execute('SELECT m.id AS message_id,s.id AS conversation_id,c.title,m.content,b.created_at'+source+' ORDER BY b.created_at DESC,m.id DESC LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size])]
        for item in items:
            item['preview']=item.pop('content')[:300]
        return {'items':items,'total':total,'page':page,'page_size':page_size}


def own_answer(conn,uid,identifier):
    row=conn.execute("SELECT m.id FROM messages m JOIN chat_sessions s ON s.id=m.session_id WHERE m.id=? AND s.account_id=? AND m.role='assistant'",(str(identifier),uid)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy câu trả lời trong hội thoại của bạn.')


@router.post('/conversations/bookmarks/{message_id}')
def bookmark(message_id:UUID,account=Depends(authenticated)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        own_answer(conn,account['id'],message_id)
        conn.execute('INSERT INTO conversation_bookmarks VALUES (?,?,?) ON CONFLICT(message_id) DO NOTHING',(str(message_id),account['id'],now()))
    return {'bookmarked':True}


@router.delete('/conversations/bookmarks/{message_id}')
def unbookmark(message_id:UUID,account=Depends(authenticated)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        own_answer(conn,account['id'],message_id)
        conn.execute('DELETE FROM conversation_bookmarks WHERE message_id=? AND account_id=?',(str(message_id),account['id']))
    return {'bookmarked':False}


@router.get('/conversations/{conversation_id}')
def conversation(conversation_id:UUID,account=Depends(authenticated)):
    with connect() as conn:
        return owned(conn,account['id'],conversation_id)


class Rename(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title:str=Field(min_length=1,max_length=120)

    @field_validator('title')
    @classmethod
    def compact(cls,value):
        return ' '.join(value.split())


@router.patch('/conversations/{conversation_id}')
def rename(conversation_id:UUID,body:Rename,account=Depends(authenticated)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned(conn,account['id'],conversation_id)
        # Rename does not reorder chronology: updated_at means latest conversation turn.
        conn.execute('UPDATE conversation_metadata SET title=?,is_title_custom=1 WHERE session_id=?',(body.title,str(conversation_id)))
        return owned(conn,account['id'],conversation_id)


@router.delete('/conversations/{conversation_id}')
def delete(conversation_id:UUID,account=Depends(authenticated)):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        owned(conn,account['id'],conversation_id)
        conn.execute('DELETE FROM chat_sessions WHERE id=? AND account_id=?',(str(conversation_id),account['id']))
    return {'deleted':True}


@router.get('/conversations/{conversation_id}/messages')
def conversation_messages(conversation_id:UUID,before:UUID|None=None,after:UUID|None=None,around:UUID|None=None,limit:int=Query(default=50,ge=1,le=100),account=Depends(authenticated)):
    if sum(value is not None for value in (before,after,around))>1:
        raise HTTPException(422,'Chỉ chọn một hướng phân trang.')
    uid,identifier=account['id'],str(conversation_id)
    with connect() as conn:
        conn.execute('BEGIN')
        info=owned(conn,uid,identifier)
        anchor=None
        if before or after or around:
            anchor=conn.execute('SELECT created_at,rowid FROM messages WHERE id=? AND session_id=?',(str(before or after or around),identifier)).fetchone()
            if not anchor:
                raise HTTPException(404,'Không tìm thấy tin nhắn trong hội thoại này.')
        def fetch(condition='',params=(),descending=True,count=limit):
            order='DESC' if descending else 'ASC'
            return conn.execute('SELECT id,rowid,created_at FROM messages WHERE session_id=?'+condition+f' ORDER BY created_at {order},rowid {order} LIMIT ?',(identifier,*params,count)).fetchall()
        if around:
            cursor=(anchor['created_at'],anchor['rowid'])
            records=list(reversed(fetch(' AND (created_at,rowid) < (?,?)',cursor,count=limit//2)))+list(fetch(' AND (created_at,rowid) >= (?,?)',cursor,descending=False,count=limit-limit//2))
        elif after:
            records=fetch(' AND (created_at,rowid) > (?,?)',(anchor['created_at'],anchor['rowid']),descending=False)
        elif before:
            records=list(reversed(fetch(' AND (created_at,rowid) < (?,?)',(anchor['created_at'],anchor['rowid']))))
        else:
            records=list(reversed(fetch()))
        items=[]
        for record in records:
            row=conn.execute(f'SELECT * FROM {relation("messages")} WHERE id=?',(record['id'],)).fetchone()
            item=decoded(row)
            item['bookmarked']=bool(conn.execute('SELECT 1 FROM conversation_bookmarks WHERE message_id=? AND account_id=?',(record['id'],uid)).fetchone())
            rating=conn.execute('SELECT rating FROM feedback WHERE message_id=?',(record['id'],)).fetchone()
            item['rating']=rating[0] if rating else None
            items.append(item)
        older=newer=False
        if records:
            first,last=records[0],records[-1]
            older=bool(fetch(' AND (created_at,rowid) < (?,?)',(first['created_at'],first['rowid']),count=1))
            newer=bool(fetch(' AND (created_at,rowid) > (?,?)',(last['created_at'],last['rowid']),descending=False,count=1))
        return {'conversation':info,'items':items,'next_before':items[0]['id'] if older else None,'next_after':items[-1]['id'] if newer else None}
