'use client';
import {FormEvent, useState} from 'react';
import Link from 'next/link';
import {api} from '../../lib/api';
import Icon from '../../components/Icon';
import UtcLogo from '../../components/UtcLogo';
import {useAuth, roleNames} from '../../components/AuthProvider';

export default function AccountPage(){
  const auth=useAuth();
  const [register,setRegister]=useState(false),[email,setEmail]=useState(''),[name,setName]=useState('');
  const [password,setPassword]=useState(''),[nextPassword,setNextPassword]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  async function submit(event:FormEvent){
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      if(register){
        await api('/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,display_name:name,password})});
        setRegister(false);setPassword('');setNotice('Đăng ký thành công. Bạn có thể đăng nhập bằng tài khoản sinh viên.');
      }else{await auth.login(email,password);setPassword('');}
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function changePassword(event:FormEvent){
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      await api('/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({current_password:password,new_password:nextPassword})});
      await auth.logout();setPassword('');setNextPassword('');setNotice('Đã đổi mật khẩu và kết thúc các phiên đăng nhập. Vui lòng đăng nhập lại.');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  const signedIn=Boolean(auth.user&&auth.user.role!=='guest');
  return <main className="account-page">
    <header className="account-header"><Link className="brand" href="/"><UtcLogo/><span>Tài khoản UTC<small>TRỢ LÝ TUYỂN SINH</small></span></Link><Link className="account-back" href="/"><span aria-hidden="true">←</span> Về hỏi đáp</Link></header>
    <div className="account-content">
      {(error||auth.error)&&<div className="error account-alert" role="alert">{error||auth.error}</div>}{notice&&<div className="notice account-alert" role="status">{notice}</div>}
      {auth.loading?<div className="account-card account-loading" role="status">Đang kiểm tra phiên đăng nhập…</div>:signedIn&&auth.user?<>
        <div className="account-heading"><div className="eyebrow">TÀI KHOẢN CỦA BẠN</div><h1>Xin chào, {auth.user.display_name||'bạn'}</h1><p>Quản lý thông tin tài khoản và truy cập các công cụ dành cho bạn.</p></div>
        <div className="account-dashboard">
          <section className="account-card account-profile" aria-labelledby="profile-title"><div className="account-card-top"><span className="account-icon"><Icon name="shield"/></span><span className="account-role">{roleNames[auth.user.role]}</span></div><h2 id="profile-title">Thông tin cá nhân</h2><dl><div><dt>Họ và tên</dt><dd>{auth.user.display_name||'Chưa cập nhật'}</dd></div><div><dt>Email</dt><dd>{auth.user.email}</dd></div><div><dt>Vai trò</dt><dd>{roleNames[auth.user.role]}</dd></div></dl></section>
          <section className="account-card account-shortcuts" aria-labelledby="shortcuts-title"><div className="account-card-top"><span className="account-icon"><Icon name="arrow"/></span></div><h2 id="shortcuts-title">Truy cập nhanh</h2><p>Tiếp tục sử dụng những công cụ phù hợp với tài khoản của bạn.</p><div className="account-link-list"><Link href="/"><Icon name="chat"/><span>Hỏi đáp tuyển sinh</span><span aria-hidden="true">→</span></Link>{auth.user.permissions.includes('content:read')&&<Link href="/admin"><Icon name="settings"/><span>Quản lý nội dung</span><span aria-hidden="true">→</span></Link>}</div></section>
          <section className="account-card account-security" aria-labelledby="security-title"><div className="account-security-intro"><div><div className="eyebrow">BẢO MẬT TÀI KHOẢN</div><h2 id="security-title">Đổi mật khẩu</h2><p>Dùng mật khẩu mới có ít nhất 16 ký tự. Sau khi đổi, bạn cần đăng nhập lại.</p></div><span className="account-icon"><Icon name="shield"/></span></div><form onSubmit={changePassword} className="account-form"><label>Mật khẩu hiện tại<input required type="password" autoComplete="current-password" maxLength={256} value={password} onChange={e=>setPassword(e.target.value)}/></label><label>Mật khẩu mới<input required type="password" autoComplete="new-password" minLength={16} maxLength={256} value={nextPassword} onChange={e=>setNextPassword(e.target.value)}/></label><button className="primary" disabled={busy}>{busy?'Đang xử lý…':'Cập nhật mật khẩu'}<Icon name="arrow"/></button></form></section>
        </div><div className="account-footer"><span>Đã đăng nhập với {auth.user.email}</span><button type="button" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await auth.logout();setPassword('');setNextPassword('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Đăng xuất</button></div>
      </>:<div className="account-auth-layout">
        <section className="account-intro" aria-labelledby="account-intro-title"><div className="account-intro-mark"><UtcLogo welcome/></div><div className="eyebrow">TRỢ LÝ TUYỂN SINH UTC</div><h1 id="account-intro-title">Một tài khoản.<br/><em>Đồng hành cùng bạn.</em></h1><p>Đăng nhập để tiếp tục hành trình tìm hiểu tuyển sinh và sử dụng các công cụ dành cho bạn.</p><div className="account-intro-note"><Icon name="shield"/><span>Khách vẫn có thể hỏi đáp và tra cứu thông tin tuyển sinh.</span></div></section>
        <form className="account-card account-auth-form" onSubmit={submit}><div className="eyebrow">{register?'BẮT ĐẦU VỚI UTC':'CHÀO MỪNG TRỞ LẠI'}</div><h2>{register?'Tạo tài khoản sinh viên':'Đăng nhập'}</h2><p>{register?'Điền thông tin bên dưới để tạo tài khoản.':'Nhập email và mật khẩu để truy cập tài khoản của bạn.'}</p>
          {register&&<label>Họ và tên<input required minLength={2} maxLength={100} autoComplete="name" value={name} onChange={e=>setName(e.target.value)} placeholder="Họ và tên của bạn"/></label>}
          <label>Email<input type="email" required maxLength={254} autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)} placeholder="ten@vidu.com"/></label>
          <label>Mật khẩu<input type="password" required minLength={register?16:1} maxLength={256} autoComplete={register?'new-password':'current-password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Nhập mật khẩu"/></label>
          {register&&<p className="account-helper">Mật khẩu cần có ít nhất 16 ký tự.</p>}
          <button className="primary account-submit" disabled={busy}>{busy?'Đang xử lý…':register?'Tạo tài khoản':'Đăng nhập'}<Icon name="arrow"/></button>
          <div className="account-switch">{register?'Đã có tài khoản?':'Chưa có tài khoản sinh viên?'} <button type="button" disabled={busy} onClick={()=>{setRegister(!register);setPassword('');setError('');setNotice('');}}>{register?'Đăng nhập':'Đăng ký ngay'}</button></div>
          <p className="account-auth-note">Tài khoản giảng viên do quản trị viên cấp.</p>
        </form>
      </div>}
    </div>
  </main>;
}
