export type Campus='hanoi'|'hcm';
export type PlannerView='calculator'|'preferences'|'checklist';
export type ScoreRule={id:string;title:string;admission_year:number;campus:Campus;subject_group:string;subjects:string[];weights:number[];priority_mode:'none'|'provided'|'taper_30';priority_cap:number;bonus_cap:number;source_url:string;scope_note:string;created_at:string};
export type Calculation={base:string;priority_applied:string;bonus:string;total:string;scale:number;year:number;campus:Campus;method:string;rule:ScoreRule|null;mode:string;formula:string;priority_formula:string;notice:string;inputs?:{scores:string[];priority:string;bonus:string;rule_id:string;program?:'other'|'english'}};
export type PlannerQuery={year?:string;campus?:string;offering?:string};
export function plannerScope(query:PlannerQuery):{initialYear?:number;initialCampus?:Campus;initialOffering:string}{
  const year=Number(query.year);
  return {
    initialYear:query.year===undefined?undefined:Number.isInteger(year)&&year>=2000&&year<=2100?year:2026,
    initialCampus:query.campus==='hanoi'||query.campus==='hcm'?query.campus:undefined,
    initialOffering:query.offering||'',
  };
}
