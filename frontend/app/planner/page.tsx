import {redirect} from 'next/navigation';
import type {PlannerQuery} from '../../lib/planner';
export default async function LegacyPlannerPage({searchParams}:{searchParams:Promise<PlannerQuery&{view?:string}>}){
  const query=await searchParams;
  const route=query.view==='preferences'?'/preferences':query.view==='checklist'?'/checklist':'/score-calculator';
  const params=new URLSearchParams();
  for(const key of ['year','campus','offering'] as const){if(query[key])params.set(key,query[key]);}
  redirect(route+(params.size?'?'+params:''));
}
