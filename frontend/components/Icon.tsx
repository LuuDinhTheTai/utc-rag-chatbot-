type Name = 'chat' | 'book' | 'chart' | 'file' | 'arrow' | 'plus' | 'shield' | 'settings' | 'calculator' | 'list' | 'calendar' | 'history' | 'bookmark' | 'search';
const paths: Record<Name, string> = {
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5a9.5 9.5 0 0 1 19 0ZM7 9h9M7 13h6',
  book: 'M12 5v16M3 3h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z',
  chart: 'M4 3v18h17M8 16v-5M13 16V7M18 16V4',
  file: 'M14 2H5v20h14V7ZM14 2v5h5M8 12h8M8 16h6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  plus: 'M12 5v14M5 12h14',
  shield: 'm12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6ZM8 12l3 3 5-6',
  history: 'M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l3 2',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM17 17l5 5',
  bookmark: 'M6 3h12v19l-6-4-6 4Z',
  calculator: 'M5 2h14v20H5ZM8 5h8v4H8ZM8 13h1M12 13h1M16 13h1M8 17h1M12 17h1M16 17h1',
  list: 'M9 5h12M9 12h12M9 19h12M3 4l1 1 2-2M3 11l1 1 2-2M3 18l1 1 2-2',
  calendar: 'M4 5h16v16H4ZM4 10h16M8 2v6M16 2v6M8 14h1M12 14h1M16 14h1M8 18h1M12 18h1',
  settings: 'M4 7h16M4 17h16M8 4v6M16 14v6',
};
export default function Icon({name}: {name: Name}) {
  return <svg className="ui-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]}/></svg>;
}
