// Phase 0 골격 표지 — G-S03 은 data-placeholder 가 0건이어야 PASS 다. 담당 개발자가 화면을 만들면서 지운다.
export default function Placeholder({no, title, owner}: {no: number; title: string; owner: string}) {
  return <section className="placeholder" data-placeholder="true">
    <h1>{no}. {title}</h1>
    <p>_placeholder — 아직 만들지 않은 화면입니다 (담당: {owner}, contracts/screen-map.md).</p>
  </section>;
}
