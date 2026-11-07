"""游戏状态管理模块。

本模块只负责“大富翁”的纯规则与数据，不依赖 pygame，方便独立测试：
- 棋盘与地块定义
- 玩家资金、位置、房产、监狱状态
- 掷骰、移动、买地、建房、收租、缴税、机会卡
- 资金不足时自动变卖资产、破产出局与胜负判断

坐标索引采用 8x8 棋盘外圈共 28 格：
0 号在左下角，顺时针经过右下角(7)、右上角(14)、左上角(21)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Optional

# ---------------------------------------------------------------------------
# 基础常量
# ---------------------------------------------------------------------------

BOARD_SIDE = 8                    # 棋盘每边格数（外圈共 28 格）
BOARD_TILES = 28                  # 棋盘总格数
START_INDEX = 0                   # 起点
JAIL_INDEX = 7                    # 监狱 / 探监
FREE_PARKING_INDEX = 14           # 免费停车
GO_TO_JAIL_INDEX = 21             # 入狱格

STARTING_CASH = 3000              # 初始资金
PASS_GO_BONUS = 120               # 经过起点奖励
MAX_LEVEL = 3                     # 地产最高等级：0 空地 / 1 小屋 / 2 洋房 / 3 酒店
RENT_MULTIPLIERS = (1, 3, 8, 14)  # 各等级租金倍率
TAX_AMOUNT = 250                  # 税务局固定税款
LEVEL_NAMES = ("空地", "小屋", "洋房", "酒店")

Color = tuple[int, int, int]

# 每个颜色组对应一个中文组名与显示颜色
GROUP_INFO: dict[str, tuple[str, Color]] = {
    "blue": ("蓝宝石区", (66, 133, 216)),
    "cyan": ("青玉区", (34, 174, 166)),
    "green": ("翡翠区", (74, 176, 98)),
    "yellow": ("黄金区", (226, 178, 50)),
    "orange": ("琥珀区", (232, 126, 55)),
    "red": ("烈焰区", (211, 76, 72)),
    "purple": ("紫罗兰区", (145, 91, 184)),
    "pink": ("樱花区", (225, 116, 158)),
}

# 特殊格的显示名称与含义
SPECIAL_KINDS = {
    "start": "起点",
    "jail": "监狱/探监",
    "free": "免费停车",
    "go_to_jail": "入狱",
    "chance": "机会",
    "tax": "税务局",
    "bonus": "福利",
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Tile:
    """棋盘上的一个格子。"""

    index: int
    name: str
    kind: str                              # property / start / chance / ...
    group: str = ""
    group_name: str = ""
    color: Color = (180, 180, 180)
    price: int = 0
    base_rent: int = 0
    build_cost: int = 0
    owner: Optional[int] = None            # 拥有者玩家下标；None 表示银行
    level: int = 0                         # 建筑等级 0~3

    @property
    def is_property(self) -> bool:
        return self.kind == "property"

    def rent_at(self, level: int) -> int:
        """返回指定建筑等级下的租金。"""
        level = max(0, min(MAX_LEVEL, level))
        return self.base_rent * RENT_MULTIPLIERS[level]

    @property
    def rent(self) -> int:
        return self.rent_at(self.level)

    @property
    def upgrade_cost(self) -> int:
        return self.build_cost


@dataclass
class Player:
    """一名玩家（人类或 AI）。"""

    index: int
    name: str
    token: str
    color: Color
    is_ai: bool
    style: str = "均衡"
    cash: int = field(default_factory=lambda: STARTING_CASH)
    position: int = START_INDEX
    properties: list[int] = field(default_factory=list)
    jail_turns: int = 0
    bankrupt: bool = False

    @property
    def in_jail(self) -> bool:
        return self.jail_turns > 0 and not self.bankrupt

    @property
    def alive(self) -> bool:
        return not self.bankrupt


@dataclass
class LogEntry:
    """一条事件日志。"""

    text: str
    kind: str = "info"
    round_no: int = 1


@dataclass
class MoveResult:
    """一次移动的结果，供画面做逐格动画。"""

    path: list[int]
    old_position: int
    new_position: int
    passed_go: bool
    dice_total: int


@dataclass
class LandingDecision:
    """落地后需要处理的决策类型。"""

    kind: str                              # buy / upgrade / rent / special / none
    tile: Tile
    can_afford: bool = True
    cost: int = 0
    detail: str = ""


@dataclass
class PaymentResult:
    """付款/破产结算结果。"""

    paid: int = 0
    bankrupt: bool = False
    liquidated: int = 0


# ---------------------------------------------------------------------------
# 棋盘定义
# ---------------------------------------------------------------------------


def _property_tile(
    index: int,
    name: str,
    group: str,
    price: int,
    base_rent: int,
) -> Tile:
    group_name, color = GROUP_INFO[group]
    return Tile(
        index=index,
        name=name,
        kind="property",
        group=group,
        group_name=group_name,
        color=color,
        price=price,
        base_rent=base_rent,
        build_cost=price // 3,
    )


def build_board() -> list[Tile]:
    """构建 28 格棋盘。每两个同色地块构成一个可集齐的地段组。"""
    return [
        Tile(START_INDEX, "起点", "start", color=(240, 202, 94)),
        _property_tile(1, "西湖路", "blue", 600, 96),
        _property_tile(2, "中山路", "blue", 640, 102),
        Tile(3, "机会", "chance", color=(95, 167, 214)),
        _property_tile(4, "解放路", "cyan", 700, 112),
        _property_tile(5, "人民路", "cyan", 740, 118),
        Tile(6, "税务局", "tax", color=(185, 105, 95)),
        Tile(JAIL_INDEX, "监狱/探监", "jail", color=(120, 126, 148)),
        _property_tile(8, "创业街", "green", 800, 128),
        _property_tile(9, "科技园", "green", 840, 134),
        Tile(10, "机会", "chance", color=(95, 167, 214)),
        _property_tile(11, "金融街", "yellow", 900, 144),
        _property_tile(12, "星河路", "yellow", 940, 150),
        _property_tile(13, "海滨路", "orange", 1000, 160),
        Tile(FREE_PARKING_INDEX, "免费停车", "free", color=(112, 178, 134)),
        _property_tile(15, "艺术街", "orange", 1040, 166),
        _property_tile(16, "港口路", "red", 1100, 176),
        Tile(17, "机会", "chance", color=(95, 167, 214)),
        _property_tile(18, "中央大道", "red", 1140, 182),
        Tile(19, "福利彩票", "bonus", color=(194, 140, 197)),
        _property_tile(20, "老城区", "purple", 1200, 192),
        Tile(GO_TO_JAIL_INDEX, "入狱", "go_to_jail", color=(152, 92, 92)),
        _property_tile(22, "高新区", "purple", 1240, 198),
        Tile(23, "机会", "chance", color=(95, 167, 214)),
        _property_tile(24, "望江路", "pink", 1300, 208),
        _property_tile(25, "湖滨路", "pink", 1340, 214),
        Tile(26, "机会", "chance", color=(95, 167, 214)),
        Tile(27, "红包雨", "bonus", color=(221, 154, 104)),
    ]


# 机会卡牌。effect 决定结算方式，文案面向玩家。
CHANCE_CARDS: list[dict] = [
    {
        "text": "银行派发年度红利，获得 250 金币。",
        "effect": "gain",
        "amount": 250,
    },
    {
        "text": "在路边捡到钱包，获得 120 金币。",
        "effect": "gain",
        "amount": 120,
    },
    {
        "text": "汽车临时维修，支付 150 金币。",
        "effect": "pay",
        "amount": 150,
    },
    {
        "text": "名下每处房产需要维修，每处支付 40 金币。",
        "effect": "repair",
        "amount": 40,
    },
    {
        "text": "搭上顺风车回到起点，并领取 200 金币。",
        "effect": "to_start",
        "amount": 200,
    },
    {
        "text": "涉嫌逃税，被直接送进监狱！",
        "effect": "jail",
        "amount": 0,
    },
    {
        "text": "投资小有收获，获得 350 金币。",
        "effect": "gain",
        "amount": 350,
    },
    {
        "text": "请朋友们吃饭，花费 180 金币。",
        "effect": "pay",
        "amount": 180,
    },
]


# ---------------------------------------------------------------------------
# 游戏主类
# ---------------------------------------------------------------------------


class MonopolyGame:
    """管理一局大富翁的完整状态与规则。"""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.tiles: list[Tile] = build_board()
        self.players: list[Player] = [
            Player(0, "你", "你", (232, 93, 86), is_ai=False, style="人类"),
            Player(1, "阿福", "福", (72, 142, 224), is_ai=True, style="稳健"),
            Player(2, "小美", "美", (72, 190, 151), is_ai=True, style="均衡"),
            Player(3, "老K", "K", (239, 180, 72), is_ai=True, style="激进"),
        ]

        self.current_index: int = 0
        self.round_no: int = 1
        self.messages: list[LogEntry] = []
        self.game_over: bool = False
        self.winner_index: Optional[int] = None
        self.eliminated_order: list[int] = []      # 先破产的排前面
        self.turn_skipped: bool = False
        self.is_double: bool = False
        self.last_dice: Optional[tuple[int, int]] = None

        # 机会卡牌洗牌后抽取，抽完重新洗牌，避免连续重复
        self._chance_order: list[int] = []
        self._build_chance_deck()

        self.log_event(f"财富大富翁开始！每人初始资金 {STARTING_CASH} 金币。", "system")
        self.log_event("买地、建房、收租，坚持到最后就是赢家。", "system")

    # ------------------------------ 基础查询 ------------------------------

    @property
    def current_player(self) -> Player:
        return self.players[self.current_index]

    @property
    def alive_players(self) -> list[Player]:
        return [p for p in self.players if p.alive]

    def player_at(self, index: int) -> Player:
        return self.players[index]

    def tile_at(self, index: int) -> Tile:
        return self.tiles[index]

    def owned_properties(self, player_index: int) -> list[Tile]:
        return [t for t in self.tiles if t.owner == player_index]

    def group_tiles(self, group: str) -> list[Tile]:
        return [t for t in self.tiles if t.group == group]

    def owns_group(self, player_index: int, group: str) -> bool:
        group_list = self.group_tiles(group)
        return bool(group_list) and all(t.owner == player_index for t in group_list)

    def net_worth(self, player: Player) -> int:
        """现金 + 房产买入价 + 建筑投入，用于界面展示。"""
        worth = player.cash
        for idx in player.properties:
            tile = self.tiles[idx]
            worth += tile.price + tile.level * tile.build_cost
        return worth

    def standings(self) -> list[Player]:
        """返回从冠军到最先出局的排名。"""
        alive = [p for p in self.players if p.alive]
        eliminated = [self.players[i] for i in reversed(self.eliminated_order)]
        return alive + eliminated

    def log_event(self, text: str, kind: str = "info") -> None:
        self.messages.append(LogEntry(text=text, kind=kind, round_no=self.round_no))
        # 日志保持有界，界面只展示尾部
        if len(self.messages) > 240:
            del self.messages[:60]

    def _build_chance_deck(self) -> None:
        self._chance_order = list(range(len(CHANCE_CARDS)))
        self.rng.shuffle(self._chance_order)

    # ------------------------------ 回合流程 ------------------------------

    def begin_turn(self) -> bool:
        """开始当前玩家回合；若在监狱则跳过，返回是否被跳过。"""
        if self.game_over:
            return True

        self.turn_skipped = False
        self.is_double = False
        self.last_dice = None
        player = self.current_player

        self.log_event(f"轮到 {player.name}（第 {self.round_no} 回合）", "turn")

        if player.jail_turns > 0:
            player.jail_turns -= 1
            self.turn_skipped = True
            if player.jail_turns == 0:
                self.log_event(f"{player.name} 刑满释放，下回合可以正常行动。", "jail")
            else:
                self.log_event(f"{player.name} 还在服刑，本回合暂停。", "jail")
            return True

        return False

    def roll_dice(self) -> tuple[int, int]:
        """为当前玩家掷两颗骰子，并记录双数状态。"""
        if self.game_over:
            return (0, 0)

        dice = (self.rng.randint(1, 6), self.rng.randint(1, 6))
        self.last_dice = dice
        self.is_double = dice[0] == dice[1]
        player = self.current_player
        extra = "（双数，可再行动一次）" if self.is_double else ""
        self.log_event(
            f"{player.name} 掷出 {dice[0]} + {dice[1]} = {sum(dice)} 点{extra}",
            "dice",
        )
        return dice

    def move_current(self) -> MoveResult:
        """按最近一次骰子点数移动当前玩家，并处理经过起点奖励。"""
        player = self.current_player
        dice_total = sum(self.last_dice or (0, 0))
        old_position = player.position
        path: list[int] = []

        position = old_position
        for _ in range(dice_total):
            position = (position + 1) % BOARD_TILES
            path.append(position)

        player.position = position
        passed_go = old_position + dice_total >= BOARD_TILES
        if passed_go:
            player.cash += PASS_GO_BONUS
            self.log_event(f"{player.name} 经过起点，领取 {PASS_GO_BONUS} 金币。", "money")

        if path:
            old_tile = self.tiles[old_position].name
            new_tile = self.tiles[position].name
            self.log_event(f"{player.name} 从「{old_tile}」移动到「{new_tile}」。", "move")
        return MoveResult(
            path=path,
            old_position=old_position,
            new_position=position,
            passed_go=passed_go,
            dice_total=dice_total,
        )

    def inspect_landing(self) -> LandingDecision:
        """检查落地格，返回需要玩家/AI 决策的类型。"""
        player = self.current_player
        tile = self.tiles[player.position]

        if tile.kind == "property":
            if tile.owner is None:
                return LandingDecision(
                    kind="buy",
                    tile=tile,
                    can_afford=player.cash >= tile.price,
                    cost=tile.price,
                )
            if tile.owner == player.index:
                can_upgrade = tile.level < MAX_LEVEL and player.cash >= tile.upgrade_cost
                if tile.level >= MAX_LEVEL:
                    return LandingDecision(kind="none", tile=tile)
                return LandingDecision(
                    kind="upgrade",
                    tile=tile,
                    can_afford=can_upgrade,
                    cost=tile.upgrade_cost,
                )
            owner = self.players[tile.owner]
            if owner.bankrupt:
                return LandingDecision(kind="special", tile=tile)
            return LandingDecision(kind="rent", tile=tile, cost=tile.rent)

        return LandingDecision(kind="special", tile=tile)

    def buy_property(self) -> bool:
        """当前玩家购买脚下无主地块。"""
        player = self.current_player
        tile = self.tiles[player.position]
        if (
            self.game_over
            or tile.kind != "property"
            or tile.owner is not None
            or player.cash < tile.price
        ):
            return False

        player.cash -= tile.price
        tile.owner = player.index
        tile.level = 0
        player.properties.append(tile.index)
        self.log_event(
            f"{player.name} 以 {tile.price} 金币买下「{tile.name}」。",
            "buy",
        )

        if self.owns_group(player.index, tile.group):
            self.log_event(
                f"{player.name} 集齐了「{tile.group_name}」全部地块！",
                "success",
            )
        return True

    def upgrade_property(self) -> bool:
        """当前玩家升级脚下属于自己的地块。"""
        player = self.current_player
        tile = self.tiles[player.position]
        if (
            self.game_over
            or tile.kind != "property"
            or tile.owner != player.index
            or tile.level >= MAX_LEVEL
            or player.cash < tile.upgrade_cost
        ):
            return False

        old_rent = tile.rent
        old_level = tile.level
        player.cash -= tile.upgrade_cost
        tile.level += 1
        self.log_event(
            f"{player.name} 花费 {tile.upgrade_cost} 金币，"
            f"把「{tile.name}」从{LEVEL_NAMES[old_level]}升级为{LEVEL_NAMES[tile.level]}，"
            f"租金 {old_rent} → {tile.rent} 金币。",
            "build",
        )
        return True

    def end_turn(self) -> str:
        """结束当前回合。双数时保留当前玩家，否则轮到下一位存活玩家。

        返回 "extra" 或 "next"，供回合循环区分。
        """
        if self.game_over:
            return "next"

        player = self.current_player
        can_extra = (
            self.is_double
            and player.alive
            and player.jail_turns == 0
        )
        if can_extra:
            self.log_event(f"{player.name} 获得额外回合。", "dice")
            return "extra"

        old_index = self.current_index
        next_index = self._next_alive_index(old_index)
        if next_index <= old_index:
            self.round_no += 1
            self.log_event(f"—— 第 {self.round_no} 回合 ——", "round")
        self.current_index = next_index
        self.is_double = False
        self.last_dice = None
        return "next"

    def _next_alive_index(self, current: int) -> int:
        """从 current 之后寻找下一位存活玩家。"""
        total = len(self.players)
        for offset in range(1, total + 1):
            candidate = (current + offset) % total
            if self.players[candidate].alive:
                return candidate
        return current

    # ------------------------------ 落地结算 ------------------------------

    def pay_rent(self) -> PaymentResult:
        """当前玩家向地块拥有者支付租金。"""
        player = self.current_player
        tile = self.tiles[player.position]
        if tile.owner is None or tile.owner == player.index:
            return PaymentResult()

        owner = self.players[tile.owner]
        rent = tile.rent
        result = self._pay(player, rent, owner, "租金")
        if not result.bankrupt:
            self.log_event(
                f"{player.name} 向 {owner.name} 支付「{tile.name}」租金 {rent} 金币"
                f"（{LEVEL_NAMES[tile.level]}）。",
                "rent",
            )
        return result

    def resolve_special(self) -> None:
        """结算当前玩家脚下的特殊格。"""
        player = self.current_player
        tile = self.tiles[player.position]

        if tile.kind == "tax":
            result = self._pay(player, TAX_AMOUNT, None, "税款")
            if not result.bankrupt:
                self.log_event(
                    f"{player.name} 在税务局缴纳 {TAX_AMOUNT} 金币。",
                    "money",
                )
        elif tile.kind == "chance":
            self._draw_chance_card(player)
        elif tile.kind == "go_to_jail":
            self._send_to_jail(player, "踩中了「入狱」格")
        elif tile.kind == "bonus":
            amount = 200 if tile.index == 19 else 150
            player.cash += amount
            self.log_event(
                f"{player.name} 在「{tile.name}」获得 {amount} 金币。",
                "money",
            )
        elif tile.kind == "free":
            self.log_event(f"{player.name} 在免费停车场休息，本回合平安无事。", "info")
        elif tile.kind == "jail":
            self.log_event(f"{player.name} 只是来探监，安全通过。", "info")
        elif tile.kind == "start":
            self.log_event(f"{player.name} 停在起点，整装待发。", "info")
        elif tile.kind == "property":
            # 无主但买不起，或自己的满级地产：给玩家一句明确反馈
            if tile.owner is None:
                self.log_event(
                    f"资金不足，{player.name} 无法购买「{tile.name}」。",
                    "warn",
                )
            elif tile.owner == player.index:
                self.log_event(
                    f"「{tile.name}」已经是{LEVEL_NAMES[tile.level]}，暂时无法继续升级。",
                    "info",
                )

    def _draw_chance_card(self, player: Player) -> None:
        if not self._chance_order:
            self._build_chance_deck()
        card = CHANCE_CARDS[self._chance_order.pop()]
        self.log_event(f"{player.name} 抽到机会卡：{card['text']}", "chance")

        effect = card["effect"]
        amount = int(card["amount"])
        if effect == "gain":
            player.cash += amount
            self.log_event(f"{player.name} 获得 {amount} 金币。", "money")
        elif effect == "pay":
            result = self._pay(player, amount, None, "机会卡支出")
            if not result.bankrupt:
                self.log_event(f"{player.name} 支付 {amount} 金币。", "money")
        elif effect == "repair":
            fee = amount * len(player.properties)
            if fee <= 0:
                self.log_event(f"{player.name} 名下没有房产，免交维修费。", "info")
                return
            result = self._pay(player, fee, None, "房产维修费")
            if not result.bankrupt:
                self.log_event(
                    f"{player.name} 为 {len(player.properties)} 处房产支付维修费 {fee} 金币。",
                    "money",
                )
        elif effect == "to_start":
            player.position = START_INDEX
            player.cash += amount
            self.log_event(
                f"{player.name} 直接回到起点，领取 {amount} 金币。",
                "move",
            )
        elif effect == "jail":
            self._send_to_jail(player, "机会卡惩罚")

    def _send_to_jail(self, player: Player, reason: str) -> None:
        player.position = JAIL_INDEX
        player.jail_turns = 1
        self.is_double = False
        self.log_event(
            f"{player.name} 因{reason}被送进监狱，将暂停一个回合。",
            "danger",
        )

    # ------------------------------ 付款与破产 ------------------------------

    def _pay(
        self,
        player: Player,
        amount: int,
        creditor: Optional[Player],
        reason: str,
    ) -> PaymentResult:
        """结算一笔支出：不足时先自动变卖，仍不足则破产。"""
        amount = max(0, amount)
        liquidated = 0
        if player.cash < amount:
            liquidated = self._liquidate(player, amount)

        if player.cash < amount:
            # 掏出最后一点现金交给债主，然后破产出局
            remaining = player.cash
            if creditor is not None and creditor.alive:
                creditor.cash += remaining
            player.cash = 0
            self._bankrupt(player, creditor, reason, amount)
            return PaymentResult(paid=remaining, bankrupt=True, liquidated=liquidated)

        player.cash -= amount
        if creditor is not None and creditor.alive:
            creditor.cash += amount
        return PaymentResult(paid=amount, bankrupt=False, liquidated=liquidated)

    def _liquidate(self, player: Player, target_cash: int) -> int:
        """自动变卖建筑和地产，尽量凑齐 target_cash，返回回笼资金。"""
        raised = 0

        # 先拆建筑：每降一级返还一半建造成本
        while player.cash < target_cash:
            candidates = [
                self.tiles[idx]
                for idx in player.properties
                if self.tiles[idx].level > 0
            ]
            if not candidates:
                break
            tile = max(candidates, key=lambda t: t.build_cost)
            refund = max(1, tile.build_cost // 2)
            tile.level -= 1
            player.cash += refund
            raised += refund
            self.log_event(
                f"资金不足，{player.name} 拆除「{tile.name}」一级建筑，回笼 {refund} 金币。",
                "warn",
            )

        # 再卖地：按买入价一半卖给银行
        while player.cash < target_cash:
            candidates = [self.tiles[idx] for idx in player.properties]
            if not candidates:
                break
            tile = min(candidates, key=lambda t: t.price)
            refund = max(1, tile.price // 2)
            tile.owner = None
            tile.level = 0
            player.properties.remove(tile.index)
            player.cash += refund
            raised += refund
            self.log_event(
                f"资金不足，{player.name} 将「{tile.name}」抵押给银行，获得 {refund} 金币。",
                "warn",
            )

        return raised

    def _bankrupt(
        self,
        player: Player,
        creditor: Optional[Player],
        reason: str,
        amount: int,
    ) -> None:
        """玩家破产：释放全部地产，记录出局顺序，并检查是否终局。"""
        if player.bankrupt:
            return

        player.bankrupt = True
        player.jail_turns = 0
        for idx in list(player.properties):
            tile = self.tiles[idx]
            tile.owner = None
            tile.level = 0
        player.properties.clear()
        self.eliminated_order.append(player.index)

        self.log_event(
            f"{player.name} 无力支付{reason} {amount} 金币，宣告破产出局！",
            "danger",
        )
        if creditor is not None:
            self.log_event(f"{player.name} 的剩余资产归 {creditor.name} 所有。", "danger")
        else:
            self.log_event(f"{player.name} 的剩余资产收归银行。", "danger")

        alive = self.alive_players
        if len(alive) <= 1:
            self.game_over = True
            self.winner_index = alive[0].index if alive else None
            if self.winner_index is not None:
                winner = self.players[self.winner_index]
                self.log_event(
                    f"游戏结束！{winner.name} 成为最后的赢家！",
                    "win",
                )
