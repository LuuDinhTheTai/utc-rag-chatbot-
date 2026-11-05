'use client';

import {memo, type ReactNode} from 'react';

type Props = {content:string; messageId:string; citations:number[]};
type Block = {kind:'paragraph'|'heading'|'quote'; text:string} |
  {kind:'list'; ordered:boolean; start:number; items:string[]};

function blocks(content:string):Block[] {
  const result:Block[] = [];
  let current:Block | undefined;
  for (const raw of content.replace(/\r\n?/g,'\n').split('\n')) {
    const line = raw.trim();
    if (!line) { current = undefined; continue; }
    const heading = /^(?:#{1,6}\s+(.+)|\*\*([^*]+)\*\*\s*:?)$/.exec(line);
    const item = /^(?:[-*•]\s+|(\d+)[.)]\s+)(.+)$/.exec(line);
    if (heading) {
      result.push({kind:'heading', text:heading[1] || heading[2]});
      current = undefined;
    } else if (item) {
      const ordered = Boolean(item[1]);
      if (current?.kind !== 'list' || current.ordered !== ordered) {
        current = {kind:'list', ordered, start:Number(item[1] || 1), items:[]};
        result.push(current);
      }
      current.items.push(item[2]);
    } else if (current?.kind === 'list' && /^\s+/.test(raw)) {
      current.items[current.items.length - 1] += '\n' + line;
    } else {
      const kind = line.startsWith('> ') ? 'quote' : 'paragraph';
      const text = kind === 'quote' ? line.slice(2) : line;
      if (current?.kind === kind) current.text += '\n' + text;
      else {
        current = {kind, text};
        result.push(current);
      }
    }
  }
  return result;
}

export default memo(function AnswerContent({content,messageId,citations}:Props) {
  function inline(text:string):ReactNode[] {
    // Only create React elements from recognized text; source HTML stays escaped.
    const pattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\)|\[\d+\])/g;
    const nodes:ReactNode[] = [];
    let offset = 0;
    for (const match of text.matchAll(pattern)) {
      const index = match.index!;
      nodes.push(text.slice(offset,index));
      const token = match[0];
      if (token.startsWith('**') || token.startsWith('__')) {
        nodes.push(<strong key={index}>{inline(token.slice(2,-2))}</strong>);
      } else if (token.startsWith('`')) {
        nodes.push(<code key={index}>{token.slice(1,-1)}</code>);
      } else {
        const link = /^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/.exec(token);
        const citation = /^\[(\d+)\]$/.exec(token);
        if (link) {
          nodes.push(<a key={index} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>);
        } else if (citation && citations.includes(Number(citation[1]))) {
          const target = `source-${messageId}-${citation[1]}`;
          nodes.push(<a key={index} className="answer-citation" href={'#'+target}
            aria-label={`Xem nguồn ${citation[1]}`} title={`Xem nguồn ${citation[1]}`}
            onClick={event=>{
              const source = document.getElementById(target);
              if (source instanceof HTMLDetailsElement) {
                event.preventDefault();
                source.open = true;
                source.scrollIntoView({block:'nearest',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
              }
            }}>{token}</a>);
        } else nodes.push(token);
      }
      offset = index + token.length;
    }
    nodes.push(text.slice(offset));
    return nodes;
  }

  return <div className="message-text answer-content">{blocks(content).map((block,index)=>{
    if (block.kind === 'list') {
      const items = block.items.map((item,i)=><li key={i}>{inline(item)}</li>);
      return block.ordered ? <ol key={index} start={block.start}>{items}</ol> : <ul key={index}>{items}</ul>;
    }
    if (block.kind === 'heading') return <h3 key={index}>{inline(block.text)}</h3>;
    if (block.kind === 'quote') return <blockquote key={index}>{inline(block.text)}</blockquote>;
    return <p key={index}>{inline(block.text)}</p>;
  })}</div>;
});
