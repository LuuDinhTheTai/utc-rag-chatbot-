import Planner from '../../components/Planner';
import {plannerScope,PlannerQuery} from '../../lib/planner';
export const metadata={title:'Checklist & lịch · UTC'};
export default async function Page({searchParams}:{searchParams:Promise<PlannerQuery>}){
  return <Planner view="checklist" {...plannerScope(await searchParams)}/>;
}
