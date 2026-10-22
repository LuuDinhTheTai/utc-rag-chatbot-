import Planner from '../../components/Planner';
import {plannerScope,PlannerQuery} from '../../lib/planner';
export const metadata={title:'Tính điểm xét tuyển · UTC'};
export default async function Page({searchParams}:{searchParams:Promise<PlannerQuery>}){
  return <Planner view="calculator" {...plannerScope(await searchParams)}/>;
}
