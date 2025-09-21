<!DOCTYPE html>
<meta charset="utf-8">
<title>Signup‧Login‧devicedata</title>
<h2>회원가입</h2>
<input id="su-email"    placeholder="email">
<input id="su-pw"       placeholder="password" type="password">
<button id="btnSU">회원가입</button>
(이메일 인증 필요 시 코드를 입력) <input id="su-code" size="6">
<button id="btnConfirm">확인</button>
<pre id="outSU"></pre>

<h2>로그인</h2>
<input id="li-email" placeholder="email">
<input id="li-pw"    placeholder="password" type="password">
<button id="btnLI">로그인</button>
<button id="btnLO">로그아웃</button>
<pre id="outLI"></pre>

<h2>devicedata 조회 (viewer 전용)</h2>
entityKey <input id="ek" size="34" placeholder="inst001#pi0001#p1002"><br>
기간&nbsp;<input id="s" placeholder="start YYYY-MM-DD"> ~ 
<input id="e" placeholder="end YYYY-MM-DD">
<button id="btnQry">조회</button>
<pre id="outDB"></pre>

<script type="module">
/* ───── Amplify v6 (ESM) 로드 ───── */
import { Amplify }      from 'https://cdn.jsdelivr.net/npm/aws-amplify@6/+esm';
import { signUp, confirmSignUp, signIn, signOut,
         fetchAuthSession }         from 'https://cdn.jsdelivr.net/npm/@aws-amplify/auth@6/+esm';

/* === 여러분 환경값으로 교체 === */
const REGION         = 'ap-northeast-2';
const USER_POOL_ID   = 'ap-northeast-2_DBPool';
const CLIENT_ID      = '8gra1p6abob8fimuauv1ajqmg';
const API_ENDPOINT   = 'https://x8dutytjjj.execute-api.ap-northeast-2.amazonaws.com/stage';

Amplify.configure({
  Auth: {
    region: REGION,
    userPoolId: USER_POOL_ID,
    userPoolClientId: CLIENT_ID,
    // 자동확인(use autoVerify or 별도 confirm 단계) 옵션은 콘솔에서 설정
  }
});

/* ---------- 회원가입 ---------- */
document.getElementById('btnSU').onclick = async ()=>{
  try{
    const email = ge('su-email'), pw = ge('su-pw');
    const { userId, nextStep } = await signUp({
      username: email, password: pw,
      options : { userAttributes:{ email } }   // 이메일 = username
    });
    out('outSU', `가입 요청 완료 → userId=${userId}\n다음 단계: ${nextStep?.signUpStep}`);
  }catch(e){ out('outSU', e); }
};

/* 이메일 코드 확인 (Auto Confirm 아니면) */
document.getElementById('btnConfirm').onclick = async ()=>{
  try{
    const ok = await confirmSignUp({
      username: ge('su-email'),
      confirmationCode: ge('su-code')
    });
    out('outSU', `확인 결과: ${ok.isSignUpComplete}`);
  }catch(e){ out('outSU', e); }
};

/* ---------- 로그인 / 로그아웃 ---------- */
document.getElementById('btnLI').onclick = async ()=>{
  try{
    const { isSignedIn } = await signIn({
      username: ge('li-email'),
      password: ge('li-pw')
    });
    if(isSignedIn){
      const { tokens } = (await fetchAuthSession()).tokens ?? {};
      out('outLI', '로그인 성공\naccessToken 앞 30자: '
                   + tokens?.accessToken.toString().slice(0,30)+'…');
    }
  }catch(e){ out('outLI', e); }
};

document.getElementById('btnLO').onclick = async ()=>{
  await signOut(); out('outLI', '로그아웃 되었습니다.');
};

/* ---------- devicedata 조회 ---------- */
document.getElementById('btnQry').onclick = async ()=>{
  const ek   = ge('ek');
  const s    = ge('s');
  const e    = ge('e');
  const qs   = new URLSearchParams({ entityKey: ek });
  if(s) qs.append('start', s);  if(e) qs.append('end', e);

  /* 현재 세션 JWT 가져오기 */
  const { tokens } = (await fetchAuthSession()).tokens ?? {};
  if(!tokens) { out('outDB', '먼저 로그인 하세요'); return; }

  const resp = await fetch(`${API_ENDPOINT}/devicedata?${qs}`,{
    headers:{ Authorization: tokens.idToken.toString() }
  });
  out('outDB', `HTTP ${resp.status}\n` + await resp.text());
};

/* ---------- 유틸 ---------- */
function ge(id){ return document.getElementById(id).value.trim(); }
function out(id,msg){ document.getElementById(id).textContent = msg; }

</script>
