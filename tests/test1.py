from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl

# 1. 创建快捷键绑定对象
kb = KeyBindings()

# 2. 绑定 Shift + Enter (写法就是 'S-enter')
@kb.add('c-m')
def _(event):
    # 当按下 Shift + Enter 时执行的逻辑
    print("\n✅ 成功捕获到  Enter！")
    event.app.exit()  # 退出应用

# 3. 创建一个简单的界面（提示用户按 Shift+Enter）
text_control = FormattedTextControl(text="请尝试按下Enter 退出程序...")
layout = Layout(Window(content=text_control))

# 4. 启动应用
app = Application(key_bindings=kb, layout=layout, full_screen=True)
app.run()