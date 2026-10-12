"""Minimal end-to-end example: one 6 s B-roll (MP4 + SFX) and one alpha 花字 overlay (MOV).
Run:  python3 example_shot.py still   -> quick JPG checks in out/_tmp
      python3 example_shot.py render  -> out/demo_broll.mp4, out/demo_overlay.mov"""
import sys
from common import *

class Demo(Shot):
    dur = 6.0; gain = 1.55; sub = 3; hud = False
    def cam(self, t):
        # slow push, then a fast whip at 3.2 s (motion blur comes from sub-frames automatically)
        k = ease_io(clamp((t - 3.2) / 0.45), 3)
        return Cam(lerp(SW / 2, SW / 2 + 110, k), SH / 2, 1.15 + 0.03 * t, roll=0.01 * k)
    def post(self, t):
        return {'dof': 0.35, 'band': 0.05}
    def draw(self, c, t):
        cam3 = Cam3(yaw=0.25 * t, pitch=0.35, dist=520, f=420, cy=SH * 0.62)
        grid3(c, cam3, y=-60, half=360, step=40, col=GREEN, alpha=0.35)
        box3(c, cam3, (0, -10, 0), (70, 70, 70), CYAN, 0.9, 1.2, fill=CYAN, fill_alpha=0.12)
        typed_plate(c, '一句话的旅行', 70, 120, 56, t, 0.3, cps=9, accent=AMBER)
        draw_text(c, 'A sentence on a journey', 72, 160, TF_EN, 24, mix(WHITE, AMBER, 0.3), ease_out((t - 1.2) / 0.3))
        pro(c, 'X: 1307 Y: 558', 420, 70, WHITE, ease_out((t - 1.6) / 0.2), size=7, lead=(380, 100))
        typed_plate(c, '第二个镜头', 330, 300, 48, t, 3.5, cps=12, accent=PINK)

def demo_events():
    ev = [(0.0, 'room', {})] + [(0.3 + i / 9, 'key', {'v': 1.2}) for i in range(6)]
    ev += [(1.2, 'blip', {'f': 1500}), (3.1, 'whoosh', {'d': 0.5, 'up': True}), (3.6, 'hit', {'v': 0.7})]
    return ev + [(3.5 + i / 12, 'key', {'v': 1.2}) for i in range(5)]

class DemoOverlay(Overlay):
    dur = 3.5
    def draw(self, c, t):
        typed_plate(c, '关键词花字', 40, 90, 40, t, 0.1, cps=10, accent=AMBER)
        if t > 1.0:
            gag(c, '梗字！', 300, 150, 28, t, 1.0)

if __name__ == '__main__':
    if sys.argv[1] == 'still':
        for t in (1.5, 3.4, 5.0):
            render_clip('demo', Demo(), still=t)
        render_overlay('demo_ov', DemoOverlay(), still=2.0)
    else:
        render_clip('demo_broll', Demo(), demo_events(), flashes=[(3.6, 0.07, (1, 0.92, 0.95))])
        render_overlay('demo_overlay', DemoOverlay(), [(0.1 + i / 10, 'key', {'v': 1.1}) for i in range(5)] + [(1.0, 'pick', {})])
