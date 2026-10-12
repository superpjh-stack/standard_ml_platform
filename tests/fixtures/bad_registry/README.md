# 불량 등록부 5종 — 병합 규칙 5 (spec §11.3 · contracts/tenant-contract.md §2.1 · G-S02)

각 폴더는 `tenant.yaml`(+ 필요 시 `tasks/` · `formulas/`) 하나로, 정상 등록부에서 **규칙 하나만** 어긴다.
`gates/check_registry.py` 가 `mlcore.registry.tenants.load_tenant(<dir>/tenant.yaml)` + `merge()` 로 읽어 기대 결과를 확인한다.
회사 코드는 가상 코드(`zz1`~`zz5`)를 쓴다 — 실 회사 이름 · 경로 오염 방지.

| 폴더 | 어기는 규칙 | 기대 |
|---|---|---|
| `r1_override_type` | R1 덮어쓰기로 `type` 변경 | `RegistryRejected(R1)` |
| `r2_missing_required_feature` | R2 live · 합성 소스 없음 · 필수 변수 원천 없음 | `RegistryRejected(R2)` |
| `r3_uses_disabled` | R3 optimize 의 의존 과제가 꺼짐 | `RegistryRejected(R3)` |
| `r4_live_synthetic` | R4 live 인데 production 이 합성 스냅숏 | 기동하되 그 과제 `disabled` (model_not_ready) — D-27 |
| `r5_plugin_conflict` | R5 같은 이름 · 다른 구현의 비용식 | `RegistryRejected(R5)` |
