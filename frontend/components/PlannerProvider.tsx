'use client';
import {createContext,useCallback,useContext,useRef,useState,ReactNode} from 'react';
import {useAuth} from './AuthProvider';
import type {Calculation,Campus} from '../lib/planner';

type State={owner:string;year:number;campus:Campus;calculation:Calculation|null};
type PlannerState=Omit<State,'owner'>&{setScope:(year:number,campus:Campus)=>void;setCalculation:(result:Calculation|null)=>void};
const Context=createContext<PlannerState|null>(null);

export default function PlannerProvider({children}:{children:ReactNode}){
  const {token}=useAuth();
  const owner=token||'guest';
  const currentOwner=useRef(owner);
  currentOwner.current=owner;
  const empty:State={owner,year:2026,campus:'hanoi',calculation:null};
  const [stored,setStored]=useState<State>(empty);
  const state=stored.owner===owner?stored:empty;
  const setCalculation=useCallback((calculation:Calculation|null)=>{
    // An outstanding request from a previous account cannot replace this account's result.
    if(currentOwner.current!==owner)return;
    setStored(previous=>({...((previous.owner===owner)?previous:{owner,year:2026,campus:'hanoi' as Campus,calculation:null}),calculation}));
  },[owner]);
  const setScope=useCallback((year:number,campus:Campus)=>{
    if(currentOwner.current!==owner)return;
    setStored(previous=>previous.owner===owner&&previous.year===year&&previous.campus===campus?previous:{owner,year,campus,calculation:null});
  },[owner]);
  return <Context.Provider value={{year:state.year,campus:state.campus,calculation:state.calculation,setScope,setCalculation}}>{children}</Context.Provider>;
}
export function usePlanner(){
  const value=useContext(Context);
  if(!value)throw new Error('PlannerProvider is required');
  return value;
}
