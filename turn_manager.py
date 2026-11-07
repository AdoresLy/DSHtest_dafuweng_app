"""回合循环与界面交互状态机。

职责：
- 驱动“开始回合 -> 掷骰 -> 移动动画 -> 落地结算 -> 决策 -> 结束回合”
- 人类玩家由按钮/空格操作，AI 按计时器自动行动
- 与渲染器解耦：本模块不直接绘制画面，只维护阶段、动画位置和待决策地块

阶段 phase 一览：
    human_roll / ai_roll_wait   等待掷骰
    rolling                     骰子动画
    moving                      棋子逐格移动
    human_buy / ai_buy_wait     购买决策
    human_upgrade / ai_upgrade_wait  建房决策
    human_end / ai_end_wait     等待结束回合
    skip_wait                   监狱跳过回合
    game_over                   终局
"""

from __future__ import annotations

import random

from ai import AIController
from game_state import MonopolyGame

AI_ROLL_DELAY = 0.62        # AI 思考后掷骰
AI_DECIDE_DELAY = 0.52      # AI 买地/建房前的停顿
AI_END_DELAY = 0.58         # AI 结束回合前停顿
SKIP_DELAY = 1.0            # 监狱跳过回合的提示时间
ROLL_ANIM_TIME = 0.52       # 骰子动画时长
MOVE_STEP_TIME = 0.065      # 每走一格的时间
MOVE_STEP_FAST = 0.045      # 超过 7 步时加快动画


class GameSession:
    """维护一局游戏从开始到结束的交互状态。"""

    def __init__(self, seed: int | None = None) -> None:
        self.ai = AIController()
        self.running = True
        self.game = MonopolyGame(seed=seed)
        self.phase = "human_roll"
        self.phase_time = 0.0
        self.timer = 0.0
        self.dice: tuple[int, int] | None = None
        self.roll_display: tuple[int, int] = (1, 1)
        self._roll_tick = 0.0
        self.render_positions: list[int] = []
        self.pending_tile: int | None = None
        self.pending_affordable = True
        self._move_path: list[int] = []
        self._move_index = 0
        self._move_step_timer = 0.0
        self._move_interval = MOVE_STEP_TIME
        self._start_new_game(seed)

    # ------------------------------ 开局/重开 ------------------------------

    def _start_new_game(self, seed: int | None = None) -> None:
        if seed is None:
            seed = random.SystemRandom().randrange(1, 2**31)
        self.game = MonopolyGame(seed=seed)
        self.phase = "start_turn"
        self.phase_time = 0.0
        self.timer = 0.0
        self.dice = None
        self.roll_display = (1, 1)
        self.pending_tile = None
        self.pending_affordable = True
        self._move_path = []
        self._move_index = 0
        self._move_step_timer = 0.0
        self._sync_positions()
        self._begin_turn()

    def restart(self) -> None:
        self._start_new_game()

    def _sync_positions(self) -> None:
        self.render_positions = [p.position for p in self.game.players]

    def _set_phase(self, phase: str, timer: float = 0.0) -> None:
        self.phase = phase
        self.phase_time = 0.0
        self.timer = timer

    # ------------------------------ 回合开始与结束 ------------------------------

    def _begin_turn(self) -> None:
        if self.game.game_over:
            self._set_phase("game_over")
            return

        skipped = self.game.begin_turn()
        self._sync_positions()
        self.dice = None
        self.roll_display = (1, 1)
        self.pending_tile = None

        if self.game.game_over:
            self._set_phase("game_over")
            return

        if skipped:
            self._set_phase("skip_wait", SKIP_DELAY)
            return

        if self.game.current_player.is_ai:
            self._set_phase("ai_roll_wait", AI_ROLL_DELAY)
        else:
            self._set_phase("human_roll")

    def _end_turn(self) -> None:
        if self.game.game_over:
            self._set_phase("game_over")
            return

        self.game.end_turn()
        self._sync_positions()
        self._begin_turn()

    # ------------------------------ 掷骰与移动 ------------------------------

    def _request_roll(self) -> None:
        if self.phase not in ("human_roll", "ai_roll_wait"):
            return
        if self.game.game_over:
            self._set_phase("game_over")
            return

        dice = self.game.roll_dice()
        self.dice = dice
        self.roll_display = dice
        self._roll_tick = 0.0
        self._set_phase("rolling", ROLL_ANIM_TIME)

    def _start_move(self) -> None:
        if self.game.game_over:
            self._set_phase("game_over")
            return

        player = self.game.current_player
        start_visual = self.render_positions[player.index]
        result = self.game.move_current()
        self._move_path = result.path
        self._move_index = 0
        self._move_step_timer = 0.0
        self._move_interval = MOVE_STEP_FAST if len(result.path) > 7 else MOVE_STEP_TIME
        self.render_positions[player.index] = start_visual
        self.roll_display = self.dice or (1, 1)
        self._set_phase("moving")
        if not result.path:
            self._finish_move()

    def _finish_move(self) -> None:
        player = self.game.current_player
        self.render_positions[player.index] = player.position
        self._resolve_landing()

    # ------------------------------ 落地结算 ------------------------------

    def _resolve_landing(self) -> None:
        if self.game.game_over:
            self._set_phase("game_over")
            return

        player = self.game.current_player
        decision = self.game.inspect_landing()
        self.pending_tile = decision.tile.index
        self.pending_affordable = decision.can_afford

        if decision.kind == "buy":
            if not decision.can_afford:
                self.game.resolve_special()
                self._finish_action()
            elif player.is_ai:
                self._set_phase("ai_buy_wait", AI_DECIDE_DELAY)
            else:
                self._set_phase("human_buy")
            return

        if decision.kind == "upgrade":
            if not decision.can_afford:
                self.game.log_event(
                    f"现金不足，{player.name} 无法升级「{decision.tile.name}」。",
                    "warn",
                )
                self._finish_action()
            elif player.is_ai:
                self._set_phase("ai_upgrade_wait", AI_DECIDE_DELAY)
            else:
                self._set_phase("human_upgrade")
            return

        if decision.kind == "rent":
            self.game.pay_rent()
            self._finish_action()
            return

        # 特殊格；可能发生瞬移（机会卡/入狱），结算后同步展示坐标
        self.game.resolve_special()
        self._sync_positions()
        self._finish_action()

    def _finish_action(self) -> None:
        """一次落地行动处理完毕，进入结束回合阶段。"""
        self.pending_tile = None
        self._sync_positions()

        if self.game.game_over:
            self._set_phase("game_over")
            return

        player = self.game.current_player
        if player.bankrupt:
            self._end_turn()
            return

        if player.is_ai:
            self._set_phase("ai_end_wait", AI_END_DELAY)
        else:
            self._set_phase("human_end")

    # ------------------------------ AI 决策 ------------------------------

    def _ai_buy(self) -> None:
        if self.phase != "ai_buy_wait" or self.pending_tile is None:
            return
        game = self.game
        player = game.current_player
        tile = game.tiles[self.pending_tile]
        should_buy, reason = self.ai.decide_buy(game, player, tile)
        game.log_event(f"{player.name} 判断：{reason}。", "ai")

        if should_buy:
            if not game.buy_property():
                game.log_event(f"{player.name} 最终没有买下「{tile.name}」。", "ai")
        else:
            game.log_event(f"{player.name} 放弃购买「{tile.name}」。", "ai")
        self._finish_action()

    def _ai_upgrade(self) -> None:
        if self.phase != "ai_upgrade_wait" or self.pending_tile is None:
            return
        game = self.game
        player = game.current_player
        tile = game.tiles[self.pending_tile]
        should_upgrade, reason = self.ai.decide_upgrade(game, player, tile)
        game.log_event(f"{player.name} 判断：{reason}。", "ai")

        if should_upgrade:
            if not game.upgrade_property():
                game.log_event(f"{player.name} 最终没有升级「{tile.name}」。", "ai")
        else:
            game.log_event(f"{player.name} 暂不升级「{tile.name}」。", "ai")
        self._finish_action()

    # ------------------------------ 人类操作 ------------------------------

    def _human_buy(self, confirm: bool) -> None:
        if self.phase != "human_buy" or self.pending_tile is None:
            return
        game = self.game
        player = game.current_player
        tile = game.tiles[self.pending_tile]

        if confirm:
            if not game.buy_property():
                game.log_event(f"购买失败，{player.name} 现金不足。", "warn")
        else:
            game.log_event(f"{player.name} 放弃购买「{tile.name}」。", "ai")
        self._finish_action()

    def _human_upgrade(self, confirm: bool) -> None:
        if self.phase != "human_upgrade" or self.pending_tile is None:
            return
        game = self.game
        player = game.current_player
        tile = game.tiles[self.pending_tile]

        if confirm:
            if not game.upgrade_property():
                game.log_event("升级失败，现金不足或已达最高等级。", "warn")
        else:
            game.log_event(f"{player.name} 暂不升级「{tile.name}」。", "ai")
        self._finish_action()

    # ------------------------------ 每帧更新 ------------------------------

    def update(self, dt: float) -> None:
        """推进计时器与动画。dt 单位为秒，由主循环传入。"""
        self.phase_time += dt
        dt = max(0.0, min(dt, 0.1))

        if self.phase == "ai_roll_wait":
            self.timer -= dt
            if self.timer <= 0:
                self._request_roll()

        elif self.phase == "rolling":
            self.timer -= dt
            self._roll_tick -= dt
            if self._roll_tick <= 0 and self.timer > 0.08:
                self.roll_display = (
                    self.game.rng.randint(1, 6),
                    self.game.rng.randint(1, 6),
                )
                self._roll_tick = 0.085
            if self.timer <= 0:
                self.roll_display = self.dice or (1, 1)
                self._start_move()

        elif self.phase == "moving":
            self._update_move(dt)

        elif self.phase == "ai_buy_wait":
            self.timer -= dt
            if self.timer <= 0:
                self._ai_buy()

        elif self.phase == "ai_upgrade_wait":
            self.timer -= dt
            if self.timer <= 0:
                self._ai_upgrade()

        elif self.phase == "ai_end_wait":
            self.timer -= dt
            if self.timer <= 0:
                self._end_turn()

        elif self.phase == "skip_wait":
            self.timer -= dt
            if self.timer <= 0:
                self._end_turn()

    def _update_move(self, dt: float) -> None:
        if not self._move_path:
            self._finish_move()
            return

        self._move_step_timer += dt
        moved = False
        while self._move_step_timer >= self._move_interval and self._move_index < len(self._move_path):
            self._move_step_timer -= self._move_interval
            self.render_positions[self.game.current_index] = self._move_path[self._move_index]
            self._move_index += 1
            moved = True

        if moved and self._move_index >= len(self._move_path):
            self._finish_move()

    # ------------------------------ 输入派发 ------------------------------

    def handle_action(self, action: str) -> None:
        """处理来自渲染层按钮或键盘的动作。"""
        if action == "quit":
            self.running = False
            return

        if action == "restart":
            if self.game.game_over:
                self.restart()
            return

        if action == "roll":
            if self.phase == "human_roll":
                self._request_roll()
            return

        if action == "end_turn":
            if self.phase == "human_end":
                self._end_turn()
            return

        if action == "buy_yes":
            self._human_buy(True)
            return
        if action == "buy_no":
            self._human_buy(False)
            return
        if action == "upgrade_yes":
            self._human_upgrade(True)
            return
        if action == "upgrade_no":
            self._human_upgrade(False)
            return

    # ------------------------------ 辅助查询 ------------------------------

    def current_hint(self) -> str:
        if self.phase == "human_roll":
            return "轮到你掷骰子"
        if self.phase == "human_end":
            return "结束回合"
        if self.phase == "game_over":
            return "游戏结束"
        return "AI 行动中"
