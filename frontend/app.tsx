// @ts-nocheck
import React, { useState, useEffect, useRef } from 'react';

// === 通信先の設定（完成したRenderのURL） ===
const API_BASE = "https://werewolf-fullstack.onrender.com/api";
const WS_BASE = "wss://werewolf-fullstack.onrender.com/ws";

// === UI定数（デザインは元のまま！） ===
const RD={villager:"村人",werewolf:"人狼",madman:"狂人",seer:"占い師",medium:"霊媒師",hunter:"狩人",fox:"妖狐",freemason:"共有者"};
const RC={villager:"#5B8C5A",werewolf:"#C0392B",madman:"#8E44AD",seer:"#2980B9",medium:"#16A085",hunter:"#D4AC0D",fox:"#E67E22",freemason:"#2E86C1"};
const REMOJI={werewolf:"🐺",seer:"🔮",hunter:"🛡️",medium:"👁️",fox:"🦊",madman:"🤡",freemason:"🤝",villager:"👤"};
const THEMES={day:{bg:"#F5F0E8",text:"#2C2416",accent:"#8B6914",border:"#E0D5C0",systemBg:"#FFF8E7",bubbleOther:"#F0EBE0",bubbleSelf:"#5B7FA5",header:"#3D3424",subtext:"#8C7B60",inputBg:"#FFF"},night:{bg:"#0F0F1E",text:"#D4D0E0",accent:"#7B68EE",border:"#2A2A45",systemBg:"#1E1E38",bubbleOther:"#222240",bubbleSelf:"#3D3080",header:"#E8E4F0",subtext:"#8880A8",inputBg:"#1A1A30"}};
const ICONS=[{s:"circle",c:"#E74C3C"},{s:"triangle",c:"#3498DB"},{s:"square",c:"#2ECC71"},{s:"diamond",c:"#F39C12"},{s:"hexagon",c:"#9B59B6"},{s:"star",c:"#1ABC9C"},{s:"pentagon",c:"#E67E22"},{s:"octagon",c:"#E91E63"},{s:"cross",c:"#00BCD4"},{s:"triangle",c:"#FF5722"},{s:"circle",c:"#8BC34A"},{s:"square",c:"#FF9800"},{s:"diamond",c:"#673AB7"},{s:"hexagon",c:"#F44336"},{s:"star",c:"#2196F3"},{s:"pentagon",c:"#4CAF50"},{s:"circle",c:"#795548"}];

function PI({i,sz=24}){const ic=ICONS[i%17],s=sz,h=s/2;const shapes={circle:<circle cx={h} cy={h} r={h*.78} fill={ic.c}/>,triangle:<polygon points={`${h},${s*.1} ${s*.88},${s*.85} ${s*.12},${s*.85}`} fill={ic.c}/>,square:<rect x={s*.14} y={s*.14} width={s*.72} height={s*.72} rx={2} fill={ic.c}/>,diamond:<polygon points={`${h},${s*.06} ${s*.88},${h} ${h},${s*.94} ${s*.12},${h}`} fill={ic.c}/>,hexagon:<polygon points={`${h},${s*.06} ${s*.88},${s*.28} ${s*.88},${s*.72} ${h},${s*.94} ${s*.12},${s*.72} ${s*.12},${s*.28}`} fill={ic.c}/>,star:<polygon points={`${h},${s*.06} ${s*.62},${s*.38} ${s*.94},${s*.4} ${s*.7},${s*.62} ${s*.8},${s*.94} ${h},${s*.75} ${s*.2},${s*.94} ${s*.3},${s*.62} ${s*.06},${s*.4} ${s*.38},${s*.38}`} fill={ic.c}/>,pentagon:<polygon points={`${h},${s*.06} ${s*.88},${s*.4} ${s*.74},${s*.9} ${s*.26},${s*.9} ${s*.12},${s*.4}`} fill={ic.c}/>,octagon:<polygon points={`${s*.3},${s*.08} ${s*.7},${s*.08} ${s*.92},${s*.3} ${s*.92},${s*.7} ${s*.7},${s*.92} ${s*.3},${s*.92} ${s*.08},${s*.7} ${s*.08},${s*.3}`} fill={ic.c}/>,cross:<path d={`M${s*.35},${s*.1}h${s*.3}v${s*.25}h${s*.25}v${s*.3}h-${s*.25}v${s*.25}h-${s*.3}v-${s*.25}h-${s*.25}v-${s*.3}h${s*.25}z`} fill={ic.c}/>};return<svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} style={{flexShrink:0}}>{shapes[ic.s]}</svg>}

// === API呼び出しのヘルパー関数 ===
async function apiCall(endpoint, payload = null) {
  const options = { method: payload ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' } };
  if (payload) options.body = JSON.stringify(payload);
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, options);
    return await res.json();
  } catch (e) {
    console.error("API Error:", e);
    return { error: "通信エラーが発生しました" };
  }
}

// === 画面コンポーネント ===
function WelcomeScreen({ onStart, isConnecting }) {
  const [n, setN] = useState("");
  return (
    <div style={{position:"fixed",inset:0,background:"linear-gradient(180deg,#0a0a1a,#1a1a3e,#0a0a2a)",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center"}}>
      <div style={{position:"relative",zIndex:1,textAlign:"center",padding:"0 28px",width:"100%",maxWidth:380}}>
        <div style={{fontSize:12,letterSpacing:6,color:"#7B68EE",marginBottom:12}}>AI WEREWOLF</div>
        <h1 style={{fontSize:38,color:"#E8E4F0",margin:"0 0 6px",fontFamily:"'Noto Serif JP',serif",textShadow:"0 0 30px rgba(123,104,238,.3)"}}>人狼ゲーム</h1>
        <p style={{color:"#8880A8",fontSize:13,margin:"0 0 36px"}}>AI 15人と挑む、本格チャット人狼</p>
        <input type="text" value={n} onChange={e=>setN(e.target.value)} placeholder="あなたの名前" maxLength={8} disabled={isConnecting} style={{width:"100%",padding:"14px 16px",fontSize:16,border:"1px solid #3A3A60",borderRadius:12,background:"rgba(20,20,50,.8)",color:"#E8E4F0",outline:"none",boxSizing:"border-box",marginBottom:14}}/>
        <button onClick={()=>n.trim()&&!isConnecting&&onStart(n.trim())} disabled={!n.trim()||isConnecting} style={{width:"100%",padding:"14px",fontSize:16,fontWeight:600,border:"none",borderRadius:12,cursor:n.trim()?"pointer":"default",background:n.trim()?"linear-gradient(135deg,#7B68EE,#5B48CE)":"#2A2A45",color:n.trim()?"#FFF":"#555"}}>
          {isConnecting ? "サーバー接続中..." : "ゲームを開始"}
        </button>
      </div>
    </div>
  );
}

function RoleRevealScreen({ roleInfo, onContinue }) {
  const [fl, setFl] = useState(false);
  useEffect(() => { setTimeout(() => setFl(true), 500) }, []);
  const role = roleInfo.role;
  const rc = RC[role] || "#888";
  return (
    <div style={{position:"fixed",inset:0,background:"linear-gradient(180deg,#0a0a1a,#1a1a3e)",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",fontFamily:"'Noto Serif JP',serif"}}>
      <p style={{color:"#8880A8",fontSize:13,marginBottom:16,letterSpacing:3}}>YOUR ROLE</p>
      <div style={{width:180,height:280,perspective:800,marginBottom:28}} onClick={()=>!fl&&setFl(true)}>
        <div style={{width:"100%",height:"100%",position:"relative",transformStyle:"preserve-3d",transition:"transform .8s",transform:fl?"rotateY(180deg)":""}}>
          <div style={{position:"absolute",inset:0,backfaceVisibility:"hidden",background:"linear-gradient(135deg,#2A2A50,#1A1A35)",borderRadius:14,border:"2px solid #3A3A60",display:"flex",alignItems:"center",justifyContent:"center"}}><span style={{fontSize:44,color:"#7B68EE"}}>?</span></div>
          <div style={{position:"absolute",inset:0,backfaceVisibility:"hidden",transform:"rotateY(180deg)",borderRadius:14,background:`linear-gradient(135deg,${rc}22,${rc}11)`,border:`2px solid ${rc}55`,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:12}}>
            <div style={{width:52,height:52,borderRadius:"50%",background:`${rc}25`,display:"flex",alignItems:"center",justifyContent:"center",marginBottom:12}}><span style={{fontSize:24}}>{REMOJI[role]||"👤"}</span></div>
            <div style={{fontSize:24,fontWeight:700,color:rc,marginBottom:6}}>{roleInfo.role_display}</div>
          </div>
        </div>
      </div>
      {fl && <button onClick={onContinue} style={{padding:"11px 36px",fontSize:14,border:"1px solid #7B68EE",borderRadius:10,background:"transparent",color:"#7B68EE",cursor:"pointer"}}>ゲームへ進む</button>}
    </div>
  );
}

function MainGame({ view, refreshView, playerId }) {
  const [input, setInput] = useState("");
  const [tab, setTab] = useState("chat");
  const [chatLog, setChatLog] = useState([]);
  const [typing, setTyping] = useState(null);
  const [overlay, setOL] = useState(null);
  const [voteTarget, setVT] = useState(null);
  const [nightTarget, setNT] = useState(null);
  const chatEnd = useRef(null);

  const phase = view.phase;
  const isNight = phase === "night" || phase === "night_transition";
  const T = isNight ? THEMES.night : THEMES.day;
  const me = view.my_info;

  // 定期更新とWebSocket
  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/${playerId}`);
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "chat_message") {
        setChatLog(prev => [...prev, msg.data]);
        refreshView();
      } else if (msg.type === "typing_start") {
        setTyping(`${msg.data.player_name}`);
      } else if (msg.type === "typing_stop") {
        setTyping(null);
      } else {
        refreshView();
      }
    };
    const timer = setInterval(() => refreshView(), 3000);
    return () => { clearInterval(timer); ws.close(); };
  }, [playerId]);

  useEffect(() => { chatEnd.current?.scrollIntoView({behavior:"smooth"}); }, [chatLog, typing]);

  const sendChat = async () => {
    if(!input.trim() || !me.is_alive) return;
    const text = input.trim();
    setInput("");
    setChatLog(prev => [...prev, { sender_id: playerId, sender_name: me.name, content: text, sys: false, self: true }]);
    await apiCall('/game/chat', { content: text, channel: "public" });
    refreshView();
  };

  const endDisc = async () => {
    await apiCall('/game/end-discussion');
    refreshView();
  };

  const execVote = async () => {
    if(!voteTarget) return;
    setOL(null);
    await apiCall('/game/vote', { target_id: voteTarget });
    refreshView();
  };

  const execNightAction = async () => {
    setOL(null);
    const type = me.role === "seer" ? "divine" : me.role === "hunter" ? "guard" : me.role === "werewolf" ? "attack" : "none";
    if (nightTarget) {
      await apiCall('/game/night-action', { action_type: type, target_id: nightTarget });
    }
    await apiCall('/game/resolve-night');
    refreshView();
  };

  const doCO = async () => {
    await apiCall('/game/co', { claimed_role: me.role });
    refreshView();
  };

  // 描画系の準備
  const alivePlayers = view.alive_players;
  
  if(phase === "game_over") {
    return (
      <div style={{position:"fixed",inset:0,background:"#1A1A1A",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:20}}>
        <h1 style={{color:"#FFF",fontSize:28,marginBottom:10}}>ゲーム終了</h1>
        <p style={{color:"#CCC",fontSize:16,marginBottom:20}}>{view.victory_reason}</p>
        <button onClick={()=>window.location.reload()} style={{padding:"12px 30px",borderRadius:10,background:"#7B68EE",color:"#FFF",border:"none",fontSize:16}}>もう一度遊ぶ</button>
      </div>
    );
  }

  return (
    <div style={{position:"fixed",inset:0,background:T.bg,color:T.text,display:"flex",flexDirection:"column"}}>
      {/* ヘッダー */}
      <div style={{padding:"7px 14px",borderBottom:`1px solid ${T.border}`,display:"flex",justifyContent:"space-between",alignItems:"center",background:isNight?"#0F0F1E":"#EDE5D5",flexShrink:0}}>
        <div>
          <span style={{fontSize:14,fontWeight:600,color:T.header}}>{view.day}日目</span>
          <span style={{marginLeft:8,fontSize:11,padding:"2px 8px",borderRadius:8,background:isNight?"#7B68EE20":`${T.accent}15`,color:isNight?"#7B68EE":T.accent}}>{phase}</span>
          {!me.is_alive && <span style={{marginLeft:6,fontSize:10,padding:"2px 6px",borderRadius:6,background:"#E74C3C20",color:"#E74C3C"}}>死亡</span>}
        </div>
        <div style={{fontSize:12,color:T.subtext}}>生存{alivePlayers.length}人</div>
      </div>

      <div style={{flex:1,display:"flex",overflow:"hidden"}}>
        {/* メインチャットエリア */}
        <div style={{flex:1,display:"flex",flexDirection:"column",overflow:"hidden"}}>
          <div style={{flex:1,overflowY:"auto",padding:"10px 14px",display:"flex",flexDirection:"column",gap:5}}>
            {chatLog.map((m, i)=>(
              <div key={i} style={{display:"flex",flexDirection:"column",alignItems:m.sys?"center":m.sender_id===playerId?"flex-end":"flex-start"}}>
                {!m.sys && m.sender_id!==playerId && <div style={{fontSize:10,color:T.subtext,marginLeft:3,marginBottom:2}}>{m.sender_name}</div>}
                <div style={{maxWidth:m.sys?"92%":"78%",padding:"7px 12px",borderRadius:m.sys?7:m.sender_id===playerId?"13px 13px 3px 13px":"13px 13px 13px 3px",background:m.sys?T.systemBg:m.sender_id===playerId?T.bubbleSelf:T.bubbleOther,color:m.sys?T.accent:m.sender_id===playerId?"#FFF":T.text,fontSize:14,lineHeight:1.5}}>
                  {m.content}
                </div>
              </div>
            ))}
            {typing && <div style={{fontSize:11,color:T.subtext,padding:"3px 6px"}}>{typing}が入力中... (AI思考中)</div>}
            <div ref={chatEnd}/>
          </div>
          
          {/* コントロールエリア */}
          {phase === "discussion" && (
            <div style={{padding:"7px 10px",borderTop:`1px solid ${T.border}`,display:"flex",flexDirection:"column",gap:7,flexShrink:0}}>
              {me.is_alive && (
                <div style={{display:"flex",gap:7}}>
                  <input type="text" value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&sendChat()} placeholder="メッセージを入力..." style={{flex:1,padding:"9px 13px",fontSize:14,borderRadius:18,border:`1px solid ${T.border}`,background:T.inputBg,color:T.text,outline:"none"}}/>
                  <button onClick={sendChat} style={{padding:"9px 14px",borderRadius:18,border:"none",background:T.accent,color:"#FFF",cursor:"pointer"}}>送信</button>
                </div>
              )}
              <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
                <button onClick={()=>setOL("vote")} style={{padding:"7px 12px",borderRadius:7,border:`1px solid ${T.accent}`,background:"transparent",color:T.accent,fontSize:12}}>投票画面を開く</button>
                {me.is_alive && ["seer","medium","hunter","freemason"].includes(me.role) && (
                  <button onClick={doCO} style={{padding:"7px 12px",borderRadius:7,border:`1px solid ${RC[me.role]}`,background:"transparent",color:RC[me.role],fontSize:12}}>COする</button>
                )}
                {me.is_alive && (
                  <button onClick={endDisc} style={{padding:"7px 12px",borderRadius:7,border:`1px solid #999`,background:"transparent",color:"#999",fontSize:12}}>議論をスキップ</button>
                )}
              </div>
            </div>
          )}
          {phase === "night" && (
            <div style={{padding:10,borderTop:`1px solid ${T.border}`,textAlign:"center"}}>
              <button onClick={()=>setOL("night_action")} style={{padding:"9px 22px",borderRadius:7,border:"none",background:"#7B68EE",color:"#FFF"}}>夜の行動を選択する</button>
            </div>
          )}
        </div>
      </div>

      {/* オーバーレイ（投票） */}
      {overlay === "vote" && (
        <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.88)",zIndex:100,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:16}}>
          <h2 style={{color:"#F0E8D0",fontSize:18,marginBottom:16}}>⚖️ 投票先を選択</h2>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(110px,1fr))",gap:8,maxWidth:460,width:"100%"}}>
            {alivePlayers.filter(p=>p.player_id!==playerId).map(p=>(
              <button key={p.player_id} onClick={()=>setVT(p.player_id)} style={{padding:"10px",borderRadius:9,border:voteTarget===p.player_id?"2px solid #D4AC0D":"1px solid #333",background:voteTarget===p.player_id?"#D4AC0D15":"#1A1812",color:"#FFF",cursor:"pointer"}}>
                {p.name}
              </button>
            ))}
          </div>
          <div style={{marginTop:20, display:"flex", gap:10}}>
            <button onClick={()=>setOL(null)} style={{padding:"11px 20px",borderRadius:9,border:"none",background:"#555",color:"#FFF"}}>閉じる</button>
            <button onClick={execVote} disabled={!voteTarget} style={{padding:"11px 32px",borderRadius:9,border:"none",background:voteTarget?"#D4AC0D":"#444",color:"#1A1812",fontWeight:600}}>投票決定</button>
          </div>
        </div>
      )}

      {/* オーバーレイ（夜行動） */}
      {overlay === "night_action" && (
        <div style={{position:"fixed",inset:0,background:"rgba(10,10,30,.95)",zIndex:100,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:16}}>
          <h2 style={{color:"#D4D0E0",fontSize:18,marginBottom:16}}>🌙 夜の行動</h2>
          {["seer", "hunter", "werewolf"].includes(me.role) ? (
            <>
              <p style={{color:"#FFF",marginBottom:10}}>対象を選んでください</p>
              <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(110px,1fr))",gap:8,maxWidth:460,width:"100%"}}>
                {alivePlayers.filter(p=>p.player_id!==playerId).map(p=>(
                  <button key={p.player_id} onClick={()=>setNT(p.player_id)} style={{padding:"10px",borderRadius:9,border:nightTarget===p.player_id?"2px solid #7B68EE":"1px solid #333",background:nightTarget===p.player_id?"#7B68EE15":"#12122A",color:"#FFF",cursor:"pointer"}}>
                    {p.name}
                  </button>
                ))}
              </div>
            </>
          ) : (
            <p style={{color:"#FFF",marginBottom:10}}>あなたの役職は夜に行うアクションがありません。</p>
          )}
          <div style={{marginTop:20, display:"flex", gap:10}}>
            <button onClick={()=>setOL(null)} style={{padding:"11px 20px",borderRadius:9,border:"none",background:"#555",color:"#FFF"}}>閉じる</button>
            <button onClick={execNightAction} style={{padding:"11px 32px",borderRadius:9,border:"none",background:"#7B68EE",color:"#FFF",fontWeight:600}}>夜を終える</button>
          </div>
        </div>
      )}
    </div>
  );
}

// === メインアプリケーション ===
export default function App() {
  const [screen, setScreen] = useState("welcome");
  const [playerId, setPlayerId] = useState(null);
  const [gameView, setGameView] = useState(null);
  const [isConnecting, setIsConnecting] = useState(false);

  const fetchView = async (id = playerId) => {
    if(!id) return;
    const data = await apiCall('/game/view');
    if (!data.error) setGameView(data);
  };

  const startGame = async (name) => {
    setIsConnecting(true);
    // 1. ゲーム作成
    const createRes = await apiCall('/game/create', { player_name: name });
    if (createRes.error) { alert("作成エラー"); setIsConnecting(false); return; }
    const newPlayerId = createRes.human_player_id;
    setPlayerId(newPlayerId);
    
    // 2. ゲーム開始（AIの準備など）
    await apiCall('/game/start');
    
    // 3. 状態を取得して画面切り替え
    const viewData = await apiCall('/game/view');
    setGameView(viewData);
    setScreen("reveal");
    setIsConnecting(false);
  };

  if (screen === "welcome") {
    return <WelcomeScreen onStart={startGame} isConnecting={isConnecting} />;
  }
  if (screen === "reveal" && gameView) {
    return <RoleRevealScreen roleInfo={gameView.my_info} onContinue={() => setScreen("game")} />;
  }
  if (screen === "game" && gameView) {
    return <MainGame view={gameView} refreshView={fetchView} playerId={playerId} />;
  }
  return <div style={{background:"#1A1A1A",color:"white",height:"100vh",display:"flex",alignItems:"center",justifyContent:"center"}}>ロード中...</div>;
}
