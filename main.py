"""财富大富翁 —— 程序入口。

运行方式：
    python main.py

依赖：Python 3.10+ 与 pygame-ce（也兼容 pygame 2.x）。
本文件只负责创建窗口、分发输入并驱动固定帧率循环。
"""

from __future__ import annotations

import sys

import pygame

from renderer import Renderer, WINDOW_HEIGHT, WINDOW_WIDTH
from turn_manager import GameSession


def _make_window_icon() -> pygame.Surface:
    """用代码生成一个简单的金币窗口图标，避免依赖外部素材。"""
    icon = pygame.Surface((64, 64), pygame.SRCALPHA)
    pygame.draw.circle(icon, (126, 84, 30), (32, 35), 29)
    pygame.draw.circle(icon, (242, 197, 92), (32, 32), 29)
    pygame.draw.circle(icon, (255, 230, 150), (32, 32), 24, 2)
    font = pygame.font.SysFont("georgia", 34, bold=True)
    text = font.render("M", True, (100, 67, 22))
    icon.blit(text, text.get_rect(center=(32, 32)))
    return icon


def main() -> int:
    pygame.init()
    pygame.display.set_caption("财富大富翁 · Monopoly")

    try:
        pygame.display.set_icon(_make_window_icon())
    except pygame.error:
        # 无显示驱动或图标设置失败时不影响游戏启动
        pass

    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    clock = pygame.time.Clock()
    renderer = Renderer(screen)
    session = GameSession()

    # 先绘制一帧，保证首帧点击也能拿到按钮区域
    renderer.draw(session)
    pygame.display.flip()

    while session.running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                session.running = False
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    session.running = False
                elif event.key == pygame.K_r and session.game.game_over:
                    session.handle_action("restart")
                elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    if session.phase == "human_roll":
                        session.handle_action("roll")
                    elif session.phase == "human_end":
                        session.handle_action("end_turn")
                continue

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                action = renderer.button_at(event.pos)
                if action:
                    session.handle_action(action)

        session.update(dt)
        renderer.draw(session)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pygame.quit()
        sys.exit(130)
