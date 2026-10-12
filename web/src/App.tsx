import {useEffect, useState} from 'react';
import {SCREENS} from './screens';

// 경로: /app/<screen>. 라우터 의존성 없이 pathname 으로 고른다.
function current(): string {
  const seg = window.location.pathname.replace(/^\/app\/?/, '').split('/')[0];
  return SCREENS.some(s => s.path === seg) ? seg : 'overview';
}

export default function App() {
  const [path, setPath] = useState(current());
  useEffect(() => {
    const onPop = () => setPath(current());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  const go = (p: string) => { window.history.pushState(null, '', `/app/${p}`); setPath(p); };
  const screen = SCREENS.find(s => s.path === path) ?? SCREENS[0];
  return <div className="shell">
    <nav aria-label="주 메뉴">
      <strong>표준 ML 플랫폼</strong>
      {SCREENS.map(s => <button key={s.path} aria-current={s.path === path ? 'page' : undefined} onClick={() => go(s.path)}>{s.no}. {s.label}</button>)}
    </nav>
    <main><screen.Component/></main>
  </div>;
}
