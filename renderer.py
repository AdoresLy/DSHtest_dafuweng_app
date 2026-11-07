"""画面渲染模块。

全部图形使用 pygame 原生绘制，不依赖图片或额外第三方库：
- 8x8 外圈棋盘、地块颜色、房屋、玩家棋子
- 右侧玩家资产面板、操作区、事件日志
- 购买/升级地产弹窗与游戏结束结算

渲染层只读取游戏状态和回合控制器的展示字段，不修改规则数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
from typing import TYPE_CHECKING, Optional

import pygame

from game_state import (
    LEVEL_NAMES,
    MAX_LEVEL,
    MonopolyGame,
    Player,
    Tile,
)

if TYPE_CHECKING:
    from turn_manager import GameSession

# ---------------------------------------------------------------------------
# 界面尺寸与配色
# ---------------------------------------------------------------------------

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
BOARD_ORIGIN = (18, 18)
TILE_SIZE = 92
BOARD_PIXELS = TILE_SIZE * 8

SIDEBAR = pygame.Rect(772, 18, 490, 764)
INNER_X = SIDEBAR.x + 16
INNER_W = SIDEBAR.width - 32

BG_TOP = (12, 20, 34)
BG_BOTTOM = (26, 38, 57)
BOARD_WOOD = (72, 50, 36)
BOARD_WOOD_LIGHT = (112, 79, 53)
SEAM = (54, 43, 35)
TILE_BG = (246, 240, 226)
TILE_SPECIAL = (234, 226, 209)
TEXT_DARK = (43, 47, 56)
TEXT_MUTED = (115, 112, 104)
CREAM = (247, 238, 215)
GOLD = (242, 197, 92)
GOLD_LIGHT = (255, 222, 139)
GREEN = (84, 178, 126)
RED = (222, 88, 83)
BLUE = (102, 164, 226)
PANEL_BG = (20, 29, 44)
CARD_BG = (30, 43, 62)
CARD_BG_ALT = (35, 49, 70)
LOG_BG = (14, 22, 35)
BUTTON_PRIMARY = (224, 174, 64)
BUTTON_PRIMARY_HOVER = (244, 197, 92)
BUTTON_SECONDARY = (47, 63, 87)
BUTTON_SECONDARY_HOVER = (61, 81, 110)
BUTTON_DANGER = (160, 67, 68)
BUTTON_DANGER_HOVER = (188, 82, 82)

LOG_COLORS = {
    "system": (167, 184, 206),
    "turn": (245, 203, 95),
    "round": (224, 173, 111),
    "dice": (122, 195, 246),
    "money": (124, 219, 151),
    "buy": (255, 198, 94),
    "build": (147, 220, 168),
    "rent": (255, 151, 137),
    "danger": (255, 105, 105),
    "jail": (173, 175, 197),
    "chance": (192, 158, 246),
    "success": (112, 234, 158),
    "win": (255, 219, 104),
    "warn": (246, 177, 92),
    "move": (173, 196, 219),
    "ai": (159, 193, 228),
    "info": (181, 192, 207),
}

DICE_PIPS = {
    1: [(0.50, 0.50)],
    2: [(0.28, 0.28), (0.72, 0.72)],
    3: [(0.26, 0.26), (0.50, 0.50), (0.74, 0.74)],
    4: [(0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)],
    5: [(0.27, 0.27), (0.73, 0.27), (0.50, 0.50), (0.27, 0.73), (0.73, 0.73)],
    6: [(0.28, 0.25), (0.72, 0.25), (0.28, 0.50), (0.72, 0.50), (0.28, 0.75), (0.72, 0.75)],
}

SPECIAL_ICONS = {
    "start": "GO",
    "jail": "牢",
    "free": "P",
    "go_to_jail": "捕",
    "chance": "?",
    "tax": "税",
    "bonus": "礼",
}


# ---------------------------------------------------------------------------
# 按钮与字体
# ---------------------------------------------------------------------------


@dataclass
class UIButton:
    rect: pygame.Rect
    label: str
    action: str
    style: str = "primary"
    enabled: bool = True


def _font_file(bold: bool) -> Optional[str]:
    """寻找一个支持中文的系统字体；找不到时退回 pygame 默认字体。"""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    bold_candidates = [
        Path(windir) / "Fonts" / "msyhbd.ttc",
        Path(windir) / "Fonts" / "simhei.ttf",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ]
    regular_candidates = [
        Path(windir) / "Fonts" / "msyh.ttc",
        Path(windir) / "Fonts" / "simhei.ttf",
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in bold_candidates if bold else regular_candidates:
        if path.exists():
            return str(path)

    names = [
        "microsoftyahei",
        "microsoftyaheiui",
        "simhei",
        "pingfangsc",
        "notosanscjksc",
        "notosanscjk",
        "wenquanyimicrohei",
        "arialunicodems",
    ]
    for name in names:
        match = pygame.font.match_font(name, bold=bold)
        if match:
            return match
    return None


# ---------------------------------------------------------------------------
# 渲染器
# ---------------------------------------------------------------------------


class Renderer:
    """把当前棋局绘制到窗口，并维护可点击按钮列表。"""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.buttons: list[UIButton] = []
        self.mouse_pos = (-1, -1)
        self._font_regular = _font_file(False)
        self._font_bold = _font_file(True) or self._font_regular
        self._font_cache: dict[tuple[int, bool], pygame.font.Font] = {}
        self.background = self._make_background()

    # ------------------------------ 基础设施 ------------------------------

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        if key not in self._font_cache:
            path = self._font_bold if bold else self._font_regular
            if path:
                self._font_cache[key] = pygame.font.Font(path, size)
            else:
                self._font_cache[key] = pygame.font.SysFont(None, size, bold=bold)
        return self._font_cache[key]

    def _make_background(self) -> pygame.Surface:
        surface = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT)).convert()
        for y in range(WINDOW_HEIGHT):
            t = y / max(1, WINDOW_HEIGHT - 1)
            color = (
                int(BG_TOP[0] * (1 - t) + BG_BOTTOM[0] * t),
                int(BG_TOP[1] * (1 - t) + BG_BOTTOM[1] * t),
                int(BG_TOP[2] * (1 - t) + BG_BOTTOM[2] * t),
            )
            pygame.draw.line(surface, color, (0, y), (WINDOW_WIDTH, y))
        # 细小的网格光点，增加桌面质感
        for x in range(22, WINDOW_WIDTH, 64):
            for y in range(26, WINDOW_HEIGHT, 64):
                pygame.draw.circle(surface, (31, 47, 69), (x, y), 1)
        return surface

    def text(
        self,
        surface: pygame.Surface,
        content: str,
        font: pygame.font.Font,
        color: tuple[int, int, int],
        pos: tuple[int, int],
        anchor: str = "topleft",
    ) -> pygame.Rect:
        image = font.render(content, True, color)
        rect = image.get_rect()
        setattr(rect, anchor, pos)
        surface.blit(image, rect)
        return rect

    def wrap(self, content: str, font: pygame.font.Font, width: int) -> list[str]:
        """按像素宽度逐字换行，适合中文日志。"""
        lines: list[str] = []
        current = ""
        for char in content:
            if char == "\n":
                lines.append(current)
                current = ""
                continue
            probe = current + char
            if current and font.size(probe)[0] > width:
                lines.append(current)
                current = char
            else:
                current = probe
        if current:
            lines.append(current)
        return lines or [""]

    def button_at(self, pos: tuple[int, int]) -> Optional[str]:
        for button in reversed(self.buttons):
            if button.enabled and button.rect.collidepoint(pos):
                return button.action
        return None

    def _add_button(
        self,
        rect: pygame.Rect,
        label: str,
        action: str,
        style: str = "primary",
        enabled: bool = True,
    ) -> None:
        self.buttons.append(UIButton(rect, label, action, style, enabled))

    def _draw_button(
        self,
        rect: pygame.Rect,
        label: str,
        action: str,
        style: str = "primary",
        enabled: bool = True,
    ) -> None:
        hovered = rect.collidepoint(self.mouse_pos) and enabled
        if style == "primary":
            color = BUTTON_PRIMARY_HOVER if hovered else BUTTON_PRIMARY
            text_color = (61, 43, 16)
        elif style == "danger":
            color = BUTTON_DANGER_HOVER if hovered else BUTTON_DANGER
            text_color = CREAM
        else:
            color = BUTTON_SECONDARY_HOVER if hovered else BUTTON_SECONDARY
            text_color = CREAM
        if not enabled:
            color = (58, 66, 78)
            text_color = (125, 134, 146)

        shadow = rect.move(0, 3)
        pygame.draw.rect(self.screen, (8, 12, 19), shadow, border_radius=10)
        pygame.draw.rect(self.screen, color, rect, border_radius=10)
        if style == "secondary" and enabled:
            pygame.draw.rect(self.screen, (92, 110, 136), rect, width=1, border_radius=10)
        font = self.font(16, bold=True)
        self.text(self.screen, label, font, text_color, rect.center, "center")
        self._add_button(rect, label, action, style, enabled)

    def _panel(
        self,
        rect: pygame.Rect,
        color: tuple[int, int, int],
        radius: int = 14,
        border: Optional[tuple[int, int, int]] = None,
        border_width: int = 1,
    ) -> None:
        pygame.draw.rect(self.screen, (7, 11, 18), rect.move(0, 4), border_radius=radius)
        pygame.draw.rect(self.screen, color, rect, border_radius=radius)
        if border:
            pygame.draw.rect(self.screen, border, rect, width=border_width, border_radius=radius)

    # ------------------------------ 总入口 ------------------------------

    def draw(self, session: "GameSession") -> None:
        self.buttons.clear()
        self.mouse_pos = pygame.mouse.get_pos()
        self.screen.blit(self.background, (0, 0))

        game = session.game
        self._draw_board(game, session)
        self._draw_sidebar(game, session)

        if game.game_over:
            self._draw_game_over(game, session)
        elif session.phase in ("human_buy", "human_upgrade"):
            self._draw_decision_overlay(game, session)

    # ------------------------------ 棋盘 ------------------------------

    def tile_rect(self, index: int) -> pygame.Rect:
        """28 格外圈坐标。0 左下，顺时针排列。"""
        x0, y0 = BOARD_ORIGIN
        if index <= 7:
            row, col = 7, index
        elif index <= 14:
            row, col = 14 - index, 7
        elif index <= 21:
            row, col = 0, 21 - index
        else:
            row, col = index - 21, 0
        return pygame.Rect(
            x0 + col * TILE_SIZE,
            y0 + row * TILE_SIZE,
            TILE_SIZE,
            TILE_SIZE,
        )

    def _draw_board(self, game: MonopolyGame, session: "GameSession") -> None:
        # 木质外框
        outer = pygame.Rect(8, 8, BOARD_PIXELS + 20, BOARD_PIXELS + 20)
        pygame.draw.rect(self.screen, (5, 8, 13), outer.move(0, 7), border_radius=12)
        pygame.draw.rect(self.screen, BOARD_WOOD, outer, border_radius=12)
        pygame.draw.rect(self.screen, BOARD_WOOD_LIGHT, outer, width=2, border_radius=12)

        current_visual_pos = session.render_positions[game.current_index]
        for tile in game.tiles:
            self._draw_tile(game, tile, current_visual_pos, session)

        self._draw_center(game, session)
        self._draw_tokens(game, session)

    def _draw_tile(
        self,
        game: MonopolyGame,
        tile: Tile,
        current_pos: int,
        session: "GameSession",
    ) -> None:
        rect = self.tile_rect(tile.index)
        inner = rect.inflate(-4, -4)
        is_current = tile.index == current_pos
        is_corner = tile.index in (0, 7, 14, 21)

        pygame.draw.rect(self.screen, SEAM, rect)
        if tile.is_property:
            base_color = TILE_BG
        elif is_corner:
            base_color = (232, 223, 204)
        else:
            base_color = TILE_SPECIAL
        pygame.draw.rect(self.screen, base_color, inner, border_radius=4)

        # 当前玩家所在格：金色呼吸描边
        if is_current:
            pulse = int(3 + (math.sin(pygame.time.get_ticks() / 220.0) + 1) * 1.5)
            pygame.draw.rect(self.screen, GOLD, inner.inflate(1, 1), width=pulse, border_radius=5)

        if tile.is_property:
            self._draw_property_tile(game, tile, inner)
        else:
            self._draw_special_tile(tile, inner)

        # 拥有者颜色描边，让棋盘归属一眼可见
        if tile.is_property and tile.owner is not None:
            owner_color = game.players[tile.owner].color
            pygame.draw.rect(self.screen, owner_color, inner, width=3, border_radius=4)

    def _draw_property_tile(self, game: MonopolyGame, tile: Tile, rect: pygame.Rect) -> None:
        # 顶部颜色条
        stripe = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, 14)
        pygame.draw.rect(self.screen, tile.color, stripe, border_top_left_radius=4, border_top_right_radius=4)
        pygame.draw.line(
            self.screen,
            (91, 86, 78),
            (rect.x + 2, stripe.bottom),
            (rect.right - 2, stripe.bottom),
            1,
        )

        name_font = self.font(13, bold=True)
        self.text(
            self.screen,
            tile.name,
            name_font,
            TEXT_DARK,
            (rect.centerx, rect.y + 30),
            "center",
        )

        # 房屋标记：小屋/洋房用绿色方块，酒店用红色长条
        if tile.level > 0:
            if tile.level < 3:
                for i in range(tile.level):
                    house = pygame.Rect(0, 0, 11, 9)
                    house.center = (rect.centerx - 8 + i * 16, rect.y + 49)
                    pygame.draw.rect(self.screen, (54, 143, 82), house, border_radius=2)
                    pygame.draw.rect(self.screen, (32, 94, 54), house, width=1, border_radius=2)
            else:
                hotel = pygame.Rect(0, 0, 28, 11)
                hotel.center = (rect.centerx, rect.y + 49)
                pygame.draw.rect(self.screen, (191, 79, 72), hotel, border_radius=2)
                pygame.draw.rect(self.screen, (116, 40, 38), hotel, width=1, border_radius=2)

        # 价格与拥有者缩写
        price_font = self.font(10, bold=False)
        self.text(
            self.screen,
            f"¥{tile.price}",
            price_font,
            (91, 83, 76),
            (rect.centerx, rect.bottom - 11),
            "center",
        )

        if tile.owner is not None:
            owner = game.players[tile.owner]
            # 用小方块标记归属，避免和棋盘上的圆形棋子混淆
            badge = pygame.Rect(rect.right - 20, rect.y + 22, 10, 10)
            pygame.draw.rect(self.screen, owner.color, badge, border_radius=2)
            pygame.draw.rect(self.screen, (250, 246, 233), badge, width=1, border_radius=2)

    def _draw_special_tile(self, tile: Tile, rect: pygame.Rect) -> None:
        icon = SPECIAL_ICONS.get(tile.kind, "?")
        icon_font = self.font(26 if tile.kind in ("start", "jail", "go_to_jail") else 25, bold=True)
        icon_color = tile.color
        if tile.kind == "start":
            icon_color = (166, 116, 28)
        elif tile.kind in ("jail", "go_to_jail"):
            icon_color = (88, 88, 102)
        elif tile.kind == "free":
            icon_color = (54, 128, 85)
        elif tile.kind == "tax":
            icon_color = (145, 71, 64)
        elif tile.kind == "chance":
            icon_color = (47, 111, 158)
        elif tile.kind == "bonus":
            icon_color = (136, 77, 140)

        self.text(
            self.screen,
            icon,
            icon_font,
            icon_color,
            (rect.centerx, rect.y + 36),
            "center",
        )

        name_font = self.font(10, bold=True)
        name = tile.name
        if tile.kind == "jail":
            name = "监狱"
        elif tile.kind == "go_to_jail":
            name = "入狱"
        self.text(
            self.screen,
            name,
            name_font,
            (91, 86, 78),
            (rect.centerx, rect.bottom - 17),
            "center",
        )

    def _draw_center(self, game: MonopolyGame, session: "GameSession") -> None:
        x, y = BOARD_ORIGIN
        center = pygame.Rect(
            x + TILE_SIZE,
            y + TILE_SIZE,
            TILE_SIZE * 6,
            TILE_SIZE * 6,
        )
        self._panel(center, (30, 81, 67), radius=8, border=(176, 143, 80), border_width=3)
        inner = center.inflate(-12, -12)
        pygame.draw.rect(self.screen, (35, 94, 76), inner, border_radius=6)
        pygame.draw.rect(self.screen, (23, 68, 55), inner, width=1, border_radius=6)

        # 四角装饰
        for corner, dx, dy in (
            (inner.topleft, 18, 18),
            (inner.topright, -18, 18),
            (inner.bottomleft, 18, -18),
            (inner.bottomright, -18, -18),
        ):
            pygame.draw.circle(self.screen, (192, 157, 87), (corner[0] + dx, corner[1] + dy), 3)

        center_x = center.centerx
        center_y = center.centery
        self.text(
            self.screen,
            "财富大富翁",
            self.font(36, bold=True),
            CREAM,
            (center_x, center_y - 168),
            "center",
        )
        self.text(
            self.screen,
            "M O N O P O L Y   ·   简 易 版",
            self.font(12, bold=True),
            (181, 205, 184),
            (center_x, center_y - 132),
            "center",
        )
        pygame.draw.line(
            self.screen,
            (108, 155, 128),
            (center_x - 150, center_y - 112),
            (center_x + 150, center_y - 112),
            1,
        )

        player = game.current_player
        self.text(
            self.screen,
            f"第 {game.round_no} 回合  ·  轮到 {player.name}",
            self.font(19, bold=True),
            player.color,
            (center_x, center_y - 82),
            "center",
        )

        # 骰子
        dice = session.roll_display if session.phase in ("rolling", "moving") else (game.last_dice or session.roll_display)
        die_size = 62
        gap = 22
        left = pygame.Rect(center_x - die_size - gap, center_y - 20, die_size, die_size)
        right = pygame.Rect(center_x + gap, center_y - 20, die_size, die_size)
        self._draw_die(left, dice[0])
        self._draw_die(right, dice[1])

        if game.last_dice:
            total = sum(game.last_dice)
            extra = "  ·  双数" if game.last_dice[0] == game.last_dice[1] else ""
            self.text(
                self.screen,
                f"本次点数 {game.last_dice[0]} + {game.last_dice[1]} = {total}{extra}",
                self.font(13, bold=False),
                (205, 221, 204),
                (center_x, center_y + 66),
                "center",
            )
        else:
            self.text(
                self.screen,
                "点击右侧按钮或按空格掷骰子",
                self.font(13, bold=False),
                (186, 207, 188),
                (center_x, center_y + 66),
                "center",
            )

        hint = self._center_hint(game, session)
        self.text(
            self.screen,
            hint,
            self.font(13, bold=True),
            GOLD_LIGHT,
            (center_x, center_y + 120),
            "center",
        )

        # 存活人数与当前资产
        alive = len(game.alive_players)
        self.text(
            self.screen,
            f"存活 {alive} 人   ·   {player.name} 现金 ¥{player.cash:,}",
            self.font(12),
            (175, 199, 181),
            (center_x, center_y + 154),
            "center",
        )

    def _center_hint(self, game: MonopolyGame, session: "GameSession") -> str:
        phase = session.phase
        if game.game_over:
            return "本局已经结束"
        if phase == "human_roll":
            return "你的回合 · 准备掷骰子"
        if phase == "ai_roll_wait":
            return f"{game.current_player.name} 正在思考…"
        if phase == "rolling":
            return "骰子滚动中…"
        if phase == "moving":
            return f"{game.current_player.name} 正在移动…"
        if phase in ("human_buy", "human_upgrade"):
            return "请查看弹出的地产卡"
        if phase == "human_end":
            return "本回合行动完成"
        if phase == "skip_wait":
            return "监狱服刑，跳过回合"
        if phase.startswith("ai_"):
            return f"{game.current_player.name} 正在行动…"
        return "游戏进行中"

    def _draw_die(self, rect: pygame.Rect, value: int) -> None:
        pygame.draw.rect(self.screen, (15, 25, 21), rect.move(3, 4), border_radius=9)
        pygame.draw.rect(self.screen, (248, 244, 231), rect, border_radius=9)
        pygame.draw.rect(self.screen, (180, 172, 152), rect, width=1, border_radius=9)
        for fx, fy in DICE_PIPS.get(value, DICE_PIPS[1]):
            center = (rect.x + int(rect.width * fx), rect.y + int(rect.height * fy))
            pygame.draw.circle(self.screen, (41, 48, 44), center, 5)

    def _draw_tokens(self, game: MonopolyGame, session: "GameSession") -> None:
        by_tile: dict[int, list[Player]] = {}
        for player in game.players:
            if player.alive:
                pos = session.render_positions[player.index]
                by_tile.setdefault(pos, []).append(player)

        offsets = {
            1: [(0, 0)],
            2: [(-10, -8), (10, 8)],
            3: [(-10, -9), (10, -6), (0, 10)],
            4: [(-10, -10), (10, -10), (-10, 10), (10, 10)],
        }

        for tile_index, players in by_tile.items():
            rect = self.tile_rect(tile_index)
            cluster_center = (rect.centerx, rect.centery + 6)
            points = offsets.get(len(players), offsets[4])
            for player, (dx, dy) in zip(players, points):
                center = (cluster_center[0] + dx, cluster_center[1] + dy)
                pygame.draw.circle(self.screen, (8, 12, 17), (center[0] + 1, center[1] + 2), 10)
                pygame.draw.circle(self.screen, player.color, center, 10)
                ring = GOLD if player.index == game.current_index else (248, 244, 230)
                pygame.draw.circle(self.screen, ring, center, 10, 2 if player.index == game.current_index else 1)
                self.text(
                    self.screen,
                    player.token,
                    self.font(8, bold=True),
                    (255, 255, 255),
                    center,
                    "center",
                )

    # ------------------------------ 侧栏 ------------------------------

    def _draw_sidebar(self, game: MonopolyGame, session: "GameSession") -> None:
        self._panel(SIDEBAR, PANEL_BG, radius=16, border=(46, 62, 83), border_width=1)

        self.text(
            self.screen,
            "财富大富翁",
            self.font(24, bold=True),
            CREAM,
            (INNER_X, SIDEBAR.y + 14),
        )
        self.text(
            self.screen,
            "桌面地产经营 · 最后存活者获胜",
            self.font(11),
            (129, 146, 169),
            (INNER_X, SIDEBAR.y + 45),
        )

        badge = pygame.Rect(INNER_X + INNER_W - 116, SIDEBAR.y + 18, 116, 32)
        pygame.draw.rect(self.screen, (42, 57, 78), badge, border_radius=9)
        pygame.draw.rect(self.screen, (72, 93, 121), badge, width=1, border_radius=9)
        self.text(
            self.screen,
            f"第 {game.round_no} 回合",
            self.font(14, bold=True),
            GOLD_LIGHT,
            badge.center,
            "center",
        )

        y = SIDEBAR.y + 70
        for player in game.players:
            self._draw_player_card(game, player, pygame.Rect(INNER_X, y, INNER_W, 74))
            y += 81

        action_top = y + 4
        action_rect = pygame.Rect(INNER_X, action_top, INNER_W, 150)
        self._draw_action_panel(game, session, action_rect)

        log_top = action_rect.bottom + 10
        log_rect = pygame.Rect(INNER_X, log_top, INNER_W, SIDEBAR.bottom - 16 - log_top)
        self._draw_log(game, log_rect)

    def _draw_player_card(
        self,
        game: MonopolyGame,
        player: Player,
        rect: pygame.Rect,
    ) -> None:
        is_current = player.index == game.current_index and not game.game_over
        fill = CARD_BG_ALT if is_current else CARD_BG
        self._panel(
            rect,
            fill,
            radius=11,
            border=GOLD if is_current else (43, 58, 79),
            border_width=2 if is_current else 1,
        )
        # 左侧玩家色条
        accent = pygame.Rect(rect.x + 1, rect.y + 1, 6, rect.height - 2)
        pygame.draw.rect(self.screen, player.color, accent, border_top_left_radius=11, border_bottom_left_radius=11)

        token_center = (rect.x + 28, rect.y + 24)
        pygame.draw.circle(self.screen, (10, 15, 22), (token_center[0] + 1, token_center[1] + 2), 14)
        pygame.draw.circle(self.screen, player.color, token_center, 14)
        pygame.draw.circle(self.screen, (243, 237, 222), token_center, 14, 1)
        self.text(
            self.screen,
            player.token,
            self.font(11, bold=True),
            (255, 255, 255),
            token_center,
            "center",
        )

        tag = "人类玩家" if not player.is_ai else f"AI · {player.style}"
        name_color = (126, 132, 145) if player.bankrupt else CREAM
        self.text(
            self.screen,
            player.name,
            self.font(16, bold=True),
            name_color,
            (rect.x + 50, rect.y + 9),
        )
        name_width = self.font(16, bold=True).size(player.name)[0]
        self.text(
            self.screen,
            tag,
            self.font(10, bold=True),
            player.color if not player.bankrupt else (120, 126, 138),
            (rect.x + 58 + name_width, rect.y + 14),
        )

        cash_color = GOLD_LIGHT if not player.bankrupt else (124, 130, 140)
        self.text(
            self.screen,
            f"¥ {player.cash:,}",
            self.font(16, bold=True),
            cash_color,
            (rect.right - 13, rect.y + 9),
            "topright",
        )

        position = game.tiles[player.position].name
        detail_color = (142, 156, 175) if not player.bankrupt else (112, 118, 130)
        self.text(
            self.screen,
            f"地产 {len(player.properties)} 处   ·   位置「{position}」",
            self.font(11),
            detail_color,
            (rect.x + 14, rect.y + 41),
        )
        self.text(
            self.screen,
            f"净资产 ¥{game.net_worth(player):,}",
            self.font(10),
            detail_color,
            (rect.x + 14, rect.y + 58),
        )

        # 状态徽标
        status = ""
        status_color = (127, 140, 160)
        if player.bankrupt:
            status = "破产出局"
            status_color = (236, 111, 111)
        elif player.in_jail:
            status = f"服刑 {player.jail_turns}"
            status_color = (173, 177, 204)
        elif is_current:
            status = "行动中"
            status_color = GOLD
        if status:
            status_font = self.font(10, bold=True)
            status_w = status_font.size(status)[0] + 14
            pill = pygame.Rect(rect.right - status_w - 12, rect.y + 47, status_w, 18)
            pygame.draw.rect(self.screen, (34, 47, 65), pill, border_radius=8)
            pygame.draw.rect(self.screen, status_color, pill, width=1, border_radius=8)
            self.text(self.screen, status, status_font, status_color, pill.center, "center")

        if player.bankrupt:
            veil = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(veil, (12, 17, 26, 92), veil.get_rect(), border_radius=11)
            self.screen.blit(veil, rect.topleft)

    def _draw_action_panel(
        self,
        game: MonopolyGame,
        session: "GameSession",
        rect: pygame.Rect,
    ) -> None:
        self._panel(rect, (25, 37, 54), radius=12, border=(45, 61, 83), border_width=1)
        self.text(
            self.screen,
            "本回合操作",
            self.font(13, bold=True),
            (186, 201, 220),
            (rect.x + 14, rect.y + 10),
        )
        player = game.current_player
        self.text(
            self.screen,
            f"{player.name}",
            self.font(12, bold=True),
            player.color,
            (rect.right - 14, rect.y + 11),
            "topright",
        )

        title, hint = self._action_text(game, session)
        self.text(
            self.screen,
            title,
            self.font(17, bold=True),
            CREAM,
            (rect.x + 14, rect.y + 34),
        )
        hint_lines = self.wrap(hint, self.font(11), rect.width - 28)
        for i, line in enumerate(hint_lines[:2]):
            self.text(
                self.screen,
                line,
                self.font(11),
                (144, 160, 181),
                (rect.x + 14, rect.y + 60 + i * 16),
            )

        phase = session.phase
        button_rect = pygame.Rect(rect.centerx - 105, rect.bottom - 48, 210, 36)
        if phase == "human_roll":
            self._draw_button(button_rect, "掷骰子   SPACE", "roll")
        elif phase == "human_end":
            self._draw_button(button_rect, "结束回合   SPACE", "end_turn")
        elif phase in ("ai_roll_wait", "ai_buy_wait", "ai_upgrade_wait", "ai_end_wait", "rolling", "moving"):
            dots = "." * (1 + int(pygame.time.get_ticks() / 350) % 3)
            self.text(
                self.screen,
                f"AI 自动行动中{dots}",
                self.font(13, bold=True),
                (111, 185, 231),
                (rect.centerx, rect.bottom - 29),
                "center",
            )
        elif phase == "skip_wait":
            self.text(
                self.screen,
                "跳过本回合…",
                self.font(13, bold=True),
                (178, 162, 205),
                (rect.centerx, rect.bottom - 29),
                "center",
            )
        elif phase in ("human_buy", "human_upgrade"):
            self.text(
                self.screen,
                "请在弹出的地产卡中选择",
                self.font(12, bold=True),
                GOLD_LIGHT,
                (rect.centerx, rect.bottom - 29),
                "center",
            )
        elif game.game_over:
            self.text(
                self.screen,
                "本局已结束",
                self.font(12, bold=True),
                (183, 158, 199),
                (rect.centerx, rect.bottom - 29),
                "center",
            )

    def _action_text(self, game: MonopolyGame, session: "GameSession") -> tuple[str, str]:
        phase = session.phase
        player = game.current_player
        if phase == "human_roll":
            return "轮到你行动", "点击掷骰子，棋子会沿棋盘前进。双数可以再行动一次。"
        if phase == "human_end":
            if game.is_double:
                return "额外回合", "你掷出了双数，结束本回合后可以再掷一次。"
            return "行动完成", "确认后轮到下一位玩家。"
        if phase == "human_buy":
            return "发现无主地产", "买入后其他玩家落到这里就要交租。"
        if phase == "human_upgrade":
            return "回到自己的地产", "可以花钱升级建筑，提高经过时的租金。"
        if phase == "rolling":
            return "掷骰中", f"{player.name} 正在掷骰子。"
        if phase == "moving":
            return "移动中", f"{player.name} 正在前进。"
        if phase == "ai_roll_wait":
            return f"{player.name} 思考中", f"{player.style}型 AI 正在评估局势。"
        if phase == "ai_buy_wait":
            return f"{player.name} 考虑买地", "AI 正在计算现金与租金回报。"
        if phase == "ai_upgrade_wait":
            return f"{player.name} 考虑建房", "AI 正在评估升级收益。"
        if phase == "ai_end_wait":
            return "AI 行动完成", "即将结束回合。"
        if phase == "skip_wait":
            return "监狱服刑", "本回合暂停，下一回合自动恢复行动。"
        if phase == "game_over":
            return "游戏结束", "查看最终排名，或重新开始一局。"
        return "准备中", "请稍候。"

    def _draw_log(self, game: MonopolyGame, rect: pygame.Rect) -> None:
        self._panel(rect, LOG_BG, radius=12, border=(40, 55, 75), border_width=1)
        self.text(
            self.screen,
            "事件日志",
            self.font(13, bold=True),
            (181, 198, 220),
            (rect.x + 14, rect.y + 9),
        )
        self.text(
            self.screen,
            f"{len(game.messages)} 条",
            self.font(10),
            (99, 117, 139),
            (rect.right - 14, rect.y + 11),
            "topright",
        )

        body = pygame.Rect(rect.x + 12, rect.y + 32, rect.width - 24, rect.height - 40)
        clip = self.screen.get_clip()
        self.screen.set_clip(body)
        font = self.font(11)
        line_h = 16
        block_gap = 4

        blocks: list[tuple[list[str], tuple[int, int, int]]] = []
        total = 0
        for entry in reversed(game.messages):
            color = LOG_COLORS.get(entry.kind, LOG_COLORS["info"])
            lines = self.wrap(f"R{entry.round_no}  {entry.text}", font, body.width)
            block_h = len(lines) * line_h + block_gap
            if total + block_h > body.height and blocks:
                break
            blocks.append((lines, color))
            total += block_h
        blocks.reverse()

        y = body.bottom - total + 2
        for lines, color in blocks:
            for line in lines:
                self.text(self.screen, line, font, color, (body.x, y))
                y += line_h
            y += block_gap
        self.screen.set_clip(clip)

    # ------------------------------ 弹窗与结束画面 ------------------------------

    def _draw_decision_overlay(
        self,
        game: MonopolyGame,
        session: "GameSession",
    ) -> None:
        tile = game.tiles[session.pending_tile] if session.pending_tile is not None else None
        if tile is None:
            return

        veil = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        veil.fill((5, 9, 15, 158))
        self.screen.blit(veil, (0, 0))

        card_w, card_h = 470, 376
        card = pygame.Rect(
            (WINDOW_WIDTH - card_w) // 2,
            (WINDOW_HEIGHT - card_h) // 2,
            card_w,
            card_h,
        )
        self._panel(card, (246, 240, 227), radius=16, border=(186, 147, 79), border_width=3)
        pygame.draw.rect(self.screen, tile.color, (card.x + 3, card.y + 3, card.width - 6, 12), border_top_left_radius=14, border_top_right_radius=14)

        is_buy = session.phase == "human_buy"
        title = "购买地产" if is_buy else "升级房产"
        subtitle = "无主地块，可立即买入" if is_buy else "让自己的地产产生更高租金"
        self.text(
            self.screen,
            title,
            self.font(26, bold=True),
            TEXT_DARK,
            (card.centerx, card.y + 34),
            "center",
        )
        self.text(
            self.screen,
            subtitle,
            self.font(11),
            (115, 107, 96),
            (card.centerx, card.y + 66),
            "center",
        )

        group_pill = pygame.Rect(card.centerx - 62, card.y + 86, 124, 22)
        pygame.draw.rect(self.screen, tile.color, group_pill, border_radius=8)
        self.text(
            self.screen,
            tile.group_name,
            self.font(10, bold=True),
            (255, 255, 255),
            group_pill.center,
            "center",
        )
        self.text(
            self.screen,
            tile.name,
            self.font(30, bold=True),
            TEXT_DARK,
            (card.centerx, card.y + 133),
            "center",
        )

        if is_buy:
            rows = [
                ("售价", f"¥{tile.price:,}"),
                ("基础租金", f"¥{tile.base_rent:,}"),
                ("升级费用", f"¥{tile.build_cost:,} / 级"),
                ("满级酒店租金", f"¥{tile.rent_at(MAX_LEVEL):,}"),
            ]
        else:
            next_level = min(MAX_LEVEL, tile.level + 1)
            rows = [
                ("当前等级", LEVEL_NAMES[tile.level]),
                ("升级到", LEVEL_NAMES[next_level]),
                ("当前租金", f"¥{tile.rent:,}"),
                ("升级后租金", f"¥{tile.rent_at(next_level):,}"),
                ("建造费用", f"¥{tile.upgrade_cost:,}"),
            ]

        start_y = card.y + 168
        for label, value in rows:
            self.text(
                self.screen,
                label,
                self.font(12),
                (124, 115, 101),
                (card.x + 74, start_y),
            )
            self.text(
                self.screen,
                value,
                self.font(13, bold=True),
                TEXT_DARK if label not in ("满级酒店租金", "升级后租金") else (47, 132, 84),
                (card.right - 74, start_y),
                "topright",
            )
            start_y += 24

        yes_label = f"购买  ¥{tile.price:,}" if is_buy else f"升级  ¥{tile.upgrade_cost:,}"
        yes_action = "buy_yes" if is_buy else "upgrade_yes"
        no_action = "buy_no" if is_buy else "upgrade_no"
        button_y = card.bottom - 62
        self._draw_button(
            pygame.Rect(card.x + 48, button_y, 178, 42),
            yes_label,
            yes_action,
            "primary",
            enabled=session.pending_affordable,
        )
        self._draw_button(
            pygame.Rect(card.right - 226, button_y, 178, 42),
            "放弃",
            no_action,
            "secondary",
        )

        if not session.pending_affordable:
            self.text(
                self.screen,
                "现金不足，无法完成这次操作",
                self.font(10, bold=True),
                RED,
                (card.centerx, card.bottom - 78),
                "center",
            )

    def _draw_game_over(self, game: MonopolyGame, session: "GameSession") -> None:
        veil = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
        veil.fill((4, 8, 14, 198))
        self.screen.blit(veil, (0, 0))

        card = pygame.Rect(320, 126, 640, 548)
        self._panel(card, (25, 37, 54), radius=18, border=(196, 158, 86), border_width=2)
        pygame.draw.rect(
            self.screen,
            (34, 50, 72),
            (card.x + 2, card.y + 2, card.width - 4, 96),
            border_top_left_radius=16,
            border_top_right_radius=16,
        )

        winner = game.players[game.winner_index] if game.winner_index is not None else game.players[0]
        self.text(
            self.screen,
            "游 戏 结 束",
            self.font(13, bold=True),
            (155, 171, 193),
            (card.centerx, card.y + 28),
            "center",
        )
        win_text = "你赢了！" if not winner.is_ai else f"{winner.name} 获胜"
        self.text(
            self.screen,
            win_text,
            self.font(38, bold=True),
            GOLD_LIGHT,
            (card.centerx, card.y + 56),
            "center",
        )

        trophy_center = (card.centerx, card.y + 142)
        pygame.draw.circle(self.screen, (47, 64, 86), trophy_center, 42)
        pygame.draw.circle(self.screen, GOLD, trophy_center, 42, 2)
        pygame.draw.circle(self.screen, winner.color, trophy_center, 28)
        self.text(
            self.screen,
            winner.token,
            self.font(20, bold=True),
            (255, 255, 255),
            trophy_center,
            "center",
        )
        self.text(
            self.screen,
            f"最终资产 ¥{game.net_worth(winner):,}",
            self.font(12, bold=True),
            (174, 194, 215),
            (card.centerx, card.y + 194),
            "center",
        )

        standings = game.standings()
        row_y = card.y + 230
        for place, player in enumerate(standings, start=1):
            row = pygame.Rect(card.x + 70, row_y, card.width - 140, 42)
            fill = (41, 57, 79) if place == 1 else (30, 42, 59)
            pygame.draw.rect(self.screen, fill, row, border_radius=8)
            if place == 1:
                pygame.draw.rect(self.screen, GOLD, row, width=1, border_radius=8)
            place_color = GOLD_LIGHT if place == 1 else (141, 157, 178)
            self.text(
                self.screen,
                f"{place}",
                self.font(15, bold=True),
                place_color,
                (row.x + 18, row.centery),
                "midleft",
            )
            pygame.draw.circle(self.screen, player.color, (row.x + 51, row.centery), 10)
            self.text(
                self.screen,
                player.token,
                self.font(8, bold=True),
                (255, 255, 255),
                (row.x + 51, row.centery),
                "center",
            )
            self.text(
                self.screen,
                player.name,
                self.font(13, bold=True),
                CREAM,
                (row.x + 70, row.centery),
                "midleft",
            )
            status = "冠军" if place == 1 else "破产出局"
            self.text(
                self.screen,
                status,
                self.font(11, bold=True),
                GOLD_LIGHT if place == 1 else (139, 146, 158),
                (row.right - 118, row.centery),
                "midright",
            )
            self.text(
                self.screen,
                f"¥{game.net_worth(player):,}",
                self.font(11, bold=True),
                (193, 207, 223),
                (row.right - 18, row.centery),
                "midright",
            )
            row_y += 49

        self._draw_button(pygame.Rect(card.centerx - 214, card.bottom - 62, 200, 42), "再来一局   R", "restart")
        self._draw_button(
            pygame.Rect(card.centerx + 14, card.bottom - 62, 200, 42),
            "退出   ESC",
            "quit",
            "secondary",
        )
