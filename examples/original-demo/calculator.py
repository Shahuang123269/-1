"""A deliberately small and safe calculator tool for the learning agent."""

from __future__ import annotations

import ast
import operator


class CalculationError(ValueError):
    """Raised when an expression is outside the calculator's small language."""


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> str:
    """Calculate basic arithmetic without using Python's unsafe ``eval`` function."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalculationError("表达式不能为空。")
    if len(expression) > 100:
        raise CalculationError("表达式过长，最多 100 个字符。")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise CalculationError("表达式格式不正确。") from error

    result = _evaluate(tree.body)
    if isinstance(result, float) and not result.is_integer():
        return f"{result:.10g}"
    return str(int(result) if isinstance(result, float) else result)


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value

    if isinstance(node, ast.UnaryOp) and type(node.op) in (ast.UAdd, ast.USub):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise CalculationError("指数的绝对值不能大于 10。")
        try:
            return _BINARY_OPERATORS[type(node.op)](left, right)
        except ZeroDivisionError as error:
            raise CalculationError("不能除以零。") from error

    raise CalculationError("只支持数字、括号和 + - * / // % ** 运算符。")
