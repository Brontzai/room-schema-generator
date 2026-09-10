"""
Черновой GUI для генератора комнат. Без claims на красоту - только чтобы
можно было пощупать руками: выбрать модель/effort, нажать "Сгенерировать",
увидеть картинку и статус проверки.

Запуск: python3 ui.py
"""
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from room_generator import generate_room

PREVIEW_SCALE = 14
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Генератор схем игровых комнат')
        self.resizable(False, False)
        self._build_widgets()
        self.seed_counter = 1

    def _build_widgets(self):
        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky='n')

        row = 0

        def add_row(label, widget):
            nonlocal row
            ttk.Label(left, text=label).grid(row=row, column=0, sticky='w', pady=3)
            widget.grid(row=row, column=1, sticky='ew', pady=3)
            row += 1

        self.width_var = tk.IntVar(value=32)
        self.height_var = tk.IntVar(value=18)
        add_row('Ширина, м', ttk.Spinbox(left, from_=16, to=64, textvariable=self.width_var, width=8))
        add_row('Высота, м', ttk.Spinbox(left, from_=10, to=40, textvariable=self.height_var, width=8))

        self.doors_var = tk.StringVar(value='авто')
        self.decor_var = tk.StringVar(value='авто')
        self.enemies_var = tk.StringVar(value='авто')
        add_row('Дверей', ttk.Spinbox(left, values=['авто', 1, 2, 3], textvariable=self.doors_var, width=8))
        add_row('Декора', ttk.Spinbox(left, values=['авто', 1, 2, 3, 4, 5, 6], textvariable=self.decor_var, width=8))
        add_row('Врагов', ttk.Spinbox(left, values=['авто', 1, 2, 3, 4, 5, 6], textvariable=self.enemies_var, width=8))

        ttk.Separator(left).grid(row=row, column=0, columnspan=2, sticky='ew', pady=8)
        row += 1

        self.ai_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text='Раскладку этажей делает Claude (AI)', variable=self.ai_var,
                         command=self._toggle_ai).grid(row=row, column=0, columnspan=2, sticky='w')
        row += 1

        self.model_var = tk.StringVar(value='haiku')
        self.effort_var = tk.StringVar(value='low')
        self.model_box = ttk.Combobox(left, textvariable=self.model_var, width=8, state='disabled',
                                       values=['haiku', 'sonnet', 'opus', 'fable'])
        self.effort_box = ttk.Combobox(left, textvariable=self.effort_var, width=8, state='disabled',
                                        values=['low', 'medium', 'high', 'xhigh', 'max'])
        add_row('Модель', self.model_box)
        add_row('Effort', self.effort_box)

        ttk.Separator(left).grid(row=row, column=0, columnspan=2, sticky='ew', pady=8)
        row += 1

        self.generate_btn = ttk.Button(left, text='Сгенерировать', command=self._on_generate)
        self.generate_btn.grid(row=row, column=0, columnspan=2, sticky='ew', pady=4)
        row += 1

        self.show_file_btn = ttk.Button(left, text='Показать файл', command=self._reveal_file, state='disabled')
        self.show_file_btn.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        row += 1
        self.last_saved_path = None

        self.status_var = tk.StringVar(value='Готов.')
        ttk.Label(left, textvariable=self.status_var, wraplength=220, justify='left',
                  foreground='#555').grid(row=row, column=0, columnspan=2, sticky='w', pady=(6, 0))

        right = ttk.Frame(self, padding=10)
        right.grid(row=0, column=1, sticky='n')
        self.canvas = tk.Canvas(right, width=32 * PREVIEW_SCALE, height=18 * PREVIEW_SCALE,
                                 bg='#eee', highlightthickness=1, highlightbackground='#999')
        self.canvas.pack()
        self._tk_img = None

    def _toggle_ai(self):
        state = 'readonly' if self.ai_var.get() else 'disabled'
        self.model_box.configure(state=state)
        self.effort_box.configure(state=state)

    def _parse_count(self, var):
        v = var.get()
        return None if v == 'авто' else int(v)

    def _on_generate(self):
        self.generate_btn.configure(state='disabled')
        self.status_var.set('Генерирую…')
        threading.Thread(target=self._generate_worker, daemon=True).start()

    def _generate_worker(self):
        seed = self.seed_counter
        self.seed_counter += 1
        try:
            room, attempts, ai_meta = generate_room(
                self.width_var.get(), self.height_var.get(), seed,
                doors=self._parse_count(self.doors_var),
                decor=self._parse_count(self.decor_var),
                enemies=self._parse_count(self.enemies_var),
                use_ai=self.ai_var.get(),
                model=self.model_var.get(),
                effort=self.effort_var.get(),
            )
            img = room.render()
            ok_palette = room.check_palette(img)
            ok_conn = room.check_connectivity()
            preview = img.resize((room.w * PREVIEW_SCALE, room.h * PREVIEW_SCALE), Image.NEAREST)

            os.makedirs(OUTPUT_DIR, exist_ok=True)
            saved_path = os.path.join(OUTPUT_DIR, f'room_seed{seed}_{ai_meta["source"]}.png')
            img.save(saved_path)  # нативный pixel-perfect PNG (1px = 1м), для конструктора
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f'Ошибка: {e}'))
            self.after(0, lambda: self.generate_btn.configure(state='normal'))
            return

        cost = ai_meta.get('cost_usd')
        lines = [
            f'seed={seed}  этажей={len(room.floors)}  декор={len(room.decor)}  враги={len(room.enemies)}',
            f'попыток={attempts}  палитра={"ok" if ok_palette else "FAIL"}  проходимость={"ok" if ok_conn else "FAIL"}',
            f'источник этажей: {ai_meta["source"]}' + (f'  (${cost:.4f})' if cost else ''),
        ]
        if ai_meta.get('error'):
            lines.append(f'AI: {ai_meta["error"]}')

        def apply():
            self._tk_img = ImageTk.PhotoImage(preview)
            self.canvas.configure(width=preview.width, height=preview.height)
            self.canvas.delete('all')
            self.canvas.create_image(0, 0, anchor='nw', image=self._tk_img)
            self.status_var.set('\n'.join(lines))
            self.generate_btn.configure(state='normal')
            self.last_saved_path = saved_path
            self.show_file_btn.configure(state='normal')

        self.after(0, apply)

    def _reveal_file(self):
        if self.last_saved_path:
            subprocess.run(['open', '-R', self.last_saved_path])


if __name__ == '__main__':
    App().mainloop()
