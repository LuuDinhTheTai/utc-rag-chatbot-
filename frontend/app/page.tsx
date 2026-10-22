import ChatWorkspace from '../components/ChatWorkspace';
export default async function ChatPage({searchParams}:{searchParams:Promise<{conversation?:string;message?:string}>}){
  const query=await searchParams;
  return <ChatWorkspace conversation={query.conversation||''} message={query.message||''}/>;
}
