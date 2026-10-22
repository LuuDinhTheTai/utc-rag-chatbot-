-- Additive migration; no session/message IDs or access tokens are replaced.
-- FTS tables are derived caches. unicode61 removes Vietnamese diacritics;
-- đ/Đ is explicitly mapped because it is a separate letter, not a diacritic.
CREATE TABLE conversation_metadata (
  session_id TEXT PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL DEFAULT 'Cuộc trò chuyện mới' CHECK(length(title) BETWEEN 1 AND 120),
  is_title_custom INTEGER NOT NULL DEFAULT 0 CHECK(is_title_custom IN (0,1)),
  updated_at TEXT NOT NULL
) STRICT;
CREATE INDEX conversation_metadata_updated ON conversation_metadata(updated_at DESC,session_id);
CREATE TABLE conversation_bookmarks (
  message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
) STRICT;
CREATE INDEX conversation_bookmarks_account ON conversation_bookmarks(account_id,created_at DESC,message_id);
CREATE VIRTUAL TABLE conversation_message_search USING fts5(content,tokenize='unicode61 remove_diacritics 2');
CREATE VIRTUAL TABLE conversation_title_search USING fts5(title,tokenize='unicode61 remove_diacritics 2');
INSERT INTO conversation_metadata(session_id,title,updated_at)
SELECT s.id,coalesce(nullif((SELECT substr(trim(replace(replace(m.content,char(10),' '),char(13),' ')),1,80)
  FROM messages m WHERE m.session_id=s.id AND m.role='user' ORDER BY m.created_at,m.rowid LIMIT 1),''),'Cuộc trò chuyện mới'),
  coalesce((SELECT max(created_at) FROM messages WHERE session_id=s.id),s.created_at)
FROM chat_sessions s;
INSERT INTO conversation_message_search(rowid,content) SELECT rowid,replace(replace(content,'đ','d'),'Đ','D') FROM messages;
INSERT INTO conversation_title_search(rowid,title) SELECT rowid,replace(replace(title,'đ','d'),'Đ','D') FROM conversation_metadata;

CREATE TRIGGER conversation_title_insert AFTER INSERT ON conversation_metadata
BEGIN
  INSERT INTO conversation_title_search(rowid,title) VALUES (NEW.rowid,replace(replace(NEW.title,'đ','d'),'Đ','D'));
END;
CREATE TRIGGER conversation_title_update AFTER UPDATE OF title ON conversation_metadata
BEGIN
  DELETE FROM conversation_title_search WHERE rowid=OLD.rowid;
  INSERT INTO conversation_title_search(rowid,title) VALUES (NEW.rowid,replace(replace(NEW.title,'đ','d'),'Đ','D'));
END;
CREATE TRIGGER conversation_title_delete AFTER DELETE ON conversation_metadata
BEGIN
  DELETE FROM conversation_title_search WHERE rowid=OLD.rowid;
END;
CREATE TRIGGER conversation_created AFTER INSERT ON chat_sessions
BEGIN
  INSERT INTO conversation_metadata(session_id,updated_at) VALUES (NEW.id,NEW.created_at);
END;
CREATE TRIGGER conversation_message_insert AFTER INSERT ON messages
BEGIN
  INSERT INTO conversation_message_search(rowid,content) VALUES (NEW.rowid,replace(replace(NEW.content,'đ','d'),'Đ','D'));
  UPDATE conversation_metadata SET
    title=CASE WHEN is_title_custom=0 AND NEW.role='user' AND
      (SELECT count(*) FROM messages WHERE session_id=NEW.session_id AND role='user')=1
      THEN coalesce(nullif(substr(trim(replace(replace(NEW.content,char(10),' '),char(13),' ')),1,80),''),'Cuộc trò chuyện mới') ELSE title END,
    updated_at=max(updated_at,NEW.created_at)
    WHERE session_id=NEW.session_id;
END;
CREATE TRIGGER conversation_message_update AFTER UPDATE OF content ON messages
BEGIN
  DELETE FROM conversation_message_search WHERE rowid=OLD.rowid;
  INSERT INTO conversation_message_search(rowid,content) VALUES (NEW.rowid,replace(replace(NEW.content,'đ','d'),'Đ','D'));
END;
CREATE TRIGGER conversation_message_delete AFTER DELETE ON messages
BEGIN
  DELETE FROM conversation_message_search WHERE rowid=OLD.rowid;
END;
CREATE TRIGGER conversation_bookmark_owner BEFORE INSERT ON conversation_bookmarks
BEGIN
  SELECT CASE WHEN NOT EXISTS (
    SELECT 1 FROM messages m JOIN chat_sessions s ON s.id=m.session_id
    WHERE m.id=NEW.message_id AND m.role='assistant' AND s.account_id=NEW.account_id
  ) THEN RAISE(ABORT,'Only the owner can bookmark an assistant answer') END;
END;
CREATE TRIGGER conversation_owner_changed AFTER UPDATE OF account_id ON chat_sessions
WHEN NEW.account_id IS NOT OLD.account_id
BEGIN
  DELETE FROM conversation_bookmarks WHERE message_id IN (SELECT id FROM messages WHERE session_id=NEW.id);
END;
INSERT INTO schema_migrations VALUES ('conversations_v1',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
