"""AI 决策模块。

三名 AI 拥有不同的风险偏好：
- 阿福：稳健，保留较多现金；
- 小美：均衡，兼顾买地与升级；
- 老K：激进，更愿意把钱投入地产。

AI 只负责给出决策和一句人类可读的理由，具体操作仍由游戏状态类执行。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅用于类型提示，避免运行时循环导入
    from game_state import MonopolyGame, Player, Tile


@dataclass(frozen=True)
class AIStyle:
    """一种 AI 风险偏好配置。"""

    name: str
    buy_reserve: int        # 买地后至少保留的现金
    upgrade_reserve: int    # 建房后至少保留的现金
    group_extra: int        # 为凑齐同色地段愿意多花的现金
    hot_cash: int           # 高于这个现金时更积极


AI_STYLES: dict[int, AIStyle] = {
    1: AIStyle("稳健", buy_reserve=1150, upgrade_reserve=1000, group_extra=260, hot_cash=3500),
    2: AIStyle("均衡", buy_reserve=780, upgrade_reserve=700, group_extra=360, hot_cash=3000),
    3: AIStyle("激进", buy_reserve=420, upgrade_reserve=420, group_extra=480, hot_cash=2200),
}


class AIController:
    """根据当前棋局做出买地与建房决策。"""

    def _style(self, player: "Player") -> AIStyle:
        return AI_STYLES.get(player.index, AIStyle("均衡", 800, 700, 350, 3000))

    def decide_buy(self, game: "MonopolyGame", player: "Player", tile: "Tile") -> tuple[bool, str]:
        """决定是否购买无主地块。返回 (是否购买, 给日志的理由)。"""
        if player.cash < tile.price:
            return False, "现金不足，无法买地"

        style = self._style(player)
        remaining = player.cash - tile.price
        group = game.group_tiles(tile.group)
        owned_in_group = sum(1 for t in group if t.owner == player.index)
        completes_group = owned_in_group == len(group) - 1
        reserve = style.buy_reserve

        # 只差一块就能集齐同色地段时，允许突破一部分现金保留线
        if completes_group:
            needed = max(120, reserve - style.group_extra)
            if remaining >= needed:
                return True, f"拿下「{tile.name}」就能集齐{tile.group_name}，果断出手"
            return False, "虽然能凑齐地段，但买完现金太少，先保命"

        # 同组已有一块，也适当提高购买意愿
        if owned_in_group > 0:
            reserve = max(150, reserve - 160)

        if remaining >= reserve:
            if remaining >= style.hot_cash and tile.price < 900:
                return True, f"现金充裕，买入「{tile.name}」收租"
            return True, f"价格合适，「{tile.name}」值得投资"

        # 激进型在低价地块上愿意冒一点现金风险
        if style.name == "激进" and tile.price <= 800 and remaining >= 160:
            return True, "低价好地，激进拿下"

        return False, "买地后现金太紧，放弃这块地"

    def decide_upgrade(
        self,
        game: "MonopolyGame",
        player: "Player",
        tile: "Tile",
    ) -> tuple[bool, str]:
        """决定是否把当前所在地产升一级。"""
        if tile.level >= 3:
            return False, "已经是酒店，无法继续升级"
        cost = tile.upgrade_cost
        if player.cash < cost:
            return False, "现金不足，无法建房"

        style = self._style(player)
        remaining = player.cash - cost
        reserve = style.upgrade_reserve
        if game.owns_group(player.index, tile.group):
            reserve = max(180, reserve - 220)

        old_rent = tile.rent
        new_rent = tile.rent_at(tile.level + 1)
        rent_gain = new_rent - old_rent
        if remaining < reserve:
            return False, "建完房后应急现金不足，暂缓建设"

        # 低等级时回本快，高等级时更看现金厚度
        if tile.level >= 2 and remaining < reserve + 500:
            return False, "高级建筑投入太大，先留现金防租金"

        if rent_gain >= max(70, cost // 4):
            return True, f"租金可从 {old_rent} 提升到 {new_rent}，值得升级"
        return True, "有闲钱就建设，长期收租更稳"
