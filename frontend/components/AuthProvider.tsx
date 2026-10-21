'use client';
import {createContext, useContext, useEffect, useState, ReactNode} from 'react';
import {api} from '../lib/api';

export type Role = 'guest' | 'student' | 'lecturer' | 'admin';
export type User = {id:string|null;email:string|null;display_name:string;role:Role;permissions:string[]};
export const roleNames:Record<Role,string> = {guest:'Khách',student:'Sinh viên',lecturer:'Giảng viên',admin:'Admin'};
type Auth = {user:User|null;token:string;loading:boolean;error:string;login:(email:string,password:string)=>Promise<void>;logout:()=>Promise<void>};
const Context=createContext<Auth|null>(null);

export default function AuthProvider({children}:{children:ReactNode}) {
  const [user,setUser]=useState<User|null>(null),[token,setToken]=useState(''),[loading,setLoading]=useState(true),[error,setError]=useState('');
  function clear(){
    sessionStorage.removeItem('utc-auth-token');
    sessionStorage.removeItem('utc-admin-token');
    localStorage.removeItem('utc-session');
    window.dispatchEvent(new Event('utc:account-changed'));
    setToken('');setUser(null);
  }
  useEffect(()=>{
    let active=true;
    const expired=()=>{clear();setError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');};
    window.addEventListener('utc:auth-expired',expired);
    const saved=sessionStorage.getItem('utc-auth-token');
    sessionStorage.removeItem('utc-admin-token');
    if(saved){
      api<User>('/auth/me').then(me=>{if(active&&sessionStorage.getItem('utc-auth-token')===saved){setUser(me);setToken(saved);}})
        .catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    } else setLoading(false);
    return()=>{active=false;window.removeEventListener('utc:auth-expired',expired);};
  },[]);
  async function login(email:string,password:string){
    const result=await api<User&{token:string}>('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});
    clear();sessionStorage.setItem('utc-auth-token',result.token);setToken(result.token);setUser(result);setError('');
  }
  async function logout(){
    await api('/auth/logout',{method:'POST'});
    clear();setError('');
  }
  return <Context.Provider value={{user,token,loading,error,login,logout}}>{children}</Context.Provider>;
}
export function useAuth(){
  const value=useContext(Context);
  if(!value)throw new Error('AuthProvider is required');
  return value;
}
