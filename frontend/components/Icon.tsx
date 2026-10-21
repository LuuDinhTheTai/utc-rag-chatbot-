type Name = 'chat' | 'book' | 'chart' | 'file' | 'arrow' | 'plus' | 'shield' | 'settings';
const paths: Record<Name, string> = {
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0ZM7 9h9M7 13h6',
  book: 'M12 5v16M3 3h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z',
  chart: 'M4 3v18h17M8 16v-5M13 16V7M18 16V4',
  file: 'M14 2H5v20h14V7ZM14 2v5h5M8 12h8M8 16h6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  plus: 'M12 5v14M5 12h14',
  shield: 'm12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6ZM8 12l3 3 5-6',
  settings: 'M4 7h16M4 17h16M8 4v6M16 14v6',
};
export default function Icon({name}: {name: Name}) {
  return <svg className="ui-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}
