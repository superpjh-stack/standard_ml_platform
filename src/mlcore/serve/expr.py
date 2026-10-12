"""안전 식 — 이름 · 숫자 · `+ - *` · 단항 부호 · 괄호만 (task-contract §2 constraints · derived · input_rules). 소유 개발2.

과제 YAML 의 식(제약 lhs/rhs · 최적화 `derived` · 입력 규칙 `input_rules`)을 같은 문법으로 읽는다.
함수 호출 · 속성 · 첨자 · 비교 · 나눗셈 · 문자열 상수는 거부한다. 값은 float 또는 numpy 배열(점마다 계산).
"""

from __future__ import annotations

import ast
from typing import Any

ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
           ast.Add, ast.Sub, ast.Mult, ast.USub, ast.UAdd)


class ExprError(ValueError):
    def __init__(self, rule: str, field: str | None = None, message: str = "식에 허용되지 않는 항이 있습니다"):
        super().__init__(message)
        self.rule, self.field = rule, field


def compile_expr(text: str) -> ast.Expression:
    try:
        tree = ast.parse(str(text), mode="eval")
    except SyntaxError:
        raise ExprError("expr_syntax") from None
    for node in ast.walk(tree):
        ok = isinstance(node, ALLOWED)
        if not ok or (isinstance(node, ast.Constant) and (isinstance(node.value, bool)
                                                          or not isinstance(node.value, (int, float)))):
            raise ExprError("expr_term")
    return tree


def names_of(tree: ast.AST) -> list[str]:
    """식에 나오는 이름(처음 나온 순서, 중복 없음)."""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in out:
            out.append(node.id)
    return out


def eval_expr(node: ast.AST, env: dict[str, Any]):
    if isinstance(node, ast.Expression):
        return eval_expr(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ExprError("expr_name", node.id, "식의 이름을 찾을 수 없습니다")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        v = eval_expr(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    a, b = eval_expr(node.left, env), eval_expr(node.right, env)
    if isinstance(node.op, ast.Add):
        return a + b
    if isinstance(node.op, ast.Sub):
        return a - b
    return a * b
