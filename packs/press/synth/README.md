# press 합성 생성기 (M2)

TODO(개발3, A0): `press_lots.py::generate(rows=720, seed=42) -> DataFrame`.
원천 `demo_data()` 와 같은 시드에서 행 일치 100%(G-M12). RNG 호출 순서는 migration/source_inventory.md §1.2.
범주 `machine_code` · `product_type`(원천 `machine` · `product`) 값은 `categories` 인자로 받는다(회사 등록부 `categories`) — 팩에 회사 설비 코드를 두지 않는다.
