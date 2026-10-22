import Planner from '../../components/Planner';
import {plannerScope,PlannerQuery} from '../../lib/planner';
export const metadata={title:'Nguyện vọng cá nhân · UTC'};
export default async function Page({searchParams}:{searchParams:Promise<PlannerQuery>}){
  return <Planner view="preferences" {...plannerScope(await searchParams)}/>;
}
