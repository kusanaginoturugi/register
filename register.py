#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
テンキーレジシステム

操作方法:
  商品コード(2桁) + [Enter]  -> 商品を選択
  数量           + [Enter]  -> カートに追加
  [00]           + [Enter]  -> お会計へ進む
  [-]            + [Enter]  -> 直前の商品をカートから削除
  [+]            + [Enter]  -> 直前の商品の数量を変更
  [/]            + [Enter]  -> 商品一覧を表示（もう一度で閉じる）
  [99]           + [Enter]  -> システム終了
  [BS]                      -> 入力を訂正（Enter前に有効）
"""

import os
import sys
import subprocess
import threading

# ============================================================
# 商品マスターデータ  コード -> (商品名, 単価)
# ============================================================
PRODUCTS = {
    "01": ("コーヒー",              300),
    "02": ("紅茶",                  280),
    "03": ("オレンジジュース",       250),
    "04": ("サンドイッチ",           450),
    "05": ("おにぎり",               150),
    "06": ("食パン",                 200),
    "07": ("ケーキ",                 500),
    "08": ("クッキー",               350),
    "09": ("ガム",                   100),
    "10": ("チョコレート",            180),
    "11": ("ポテトチップス",          220),
    "12": ("コーラ",                 150),
    "13": ("緑茶ペットボトル",        130),
    "14": ("ミネラルウォーター",      100),
    "15": ("アイスクリーム",          280),
    "20": ("日替わり弁当A",           600),
    "21": ("日替わり弁当B",           550),
    "22": ("日替わり弁当C",           480),
    "30": ("週刊誌",                 550),
    "31": ("月刊誌",                 850),
}

W = 52  # 表示幅

# ============================================================
# 効果音
# sounddevice + numpy で音を生成（pip install sounddevice numpy）
# インストールされていない場合は beep コマンド → \a にフォールバック
# ============================================================

def _try_import_audio():
    try:
        import sounddevice as sd
        import numpy as np
        return sd, np
    except ImportError:
        return None, None

def _play_async(fn):
    threading.Thread(target=fn, daemon=True).start()

def play_beep():
    """バーコードスキャナ風ビープ（商品登録確定）"""
    sd, np = _try_import_audio()
    if sd and np:
        def _play():
            try:
                sr = 44100
                dur = 0.12
                t = np.linspace(0, dur, int(sr * dur), endpoint=False)
                wave = np.sin(2 * np.pi * 1800 * t)
                env  = np.exp(-t / 0.035)          # 急速減衰
                out  = (wave * env * 0.28).astype(np.float32)
                sd.play(out, sr); sd.wait()
            except Exception:
                pass
        _play_async(_play)
    else:
        # フォールバック: beep コマンド → ターミナルベル
        def _fallback():
            try:
                subprocess.run(['beep', '-f', '1800', '-l', '110'],
                               capture_output=True, timeout=2)
            except Exception:
                sys.stdout.write('\a'); sys.stdout.flush()
        _play_async(_fallback)

def play_drawer():
    """レジドロワー風サウンド（カッ + チーン）"""
    sd, np = _try_import_audio()
    if sd and np:
        def _play():
            try:
                sr = 44100

                # 「カッ」― ノイズバースト（クリック音）
                c_dur = 0.04
                t_c   = np.linspace(0, c_dur, int(sr * c_dur), endpoint=False)
                noise = np.random.uniform(-1, 1, len(t_c))
                noise = np.convolve(noise, np.ones(18) / 18, mode='same')  # 簡易LPF
                click = noise * np.exp(-t_c / (c_dur * 0.25)) * 0.65

                # 「チーン」― ベル音（基音 1400Hz + 倍音 2300Hz）
                b_dur = 0.95
                t_b   = np.linspace(0, b_dur, int(sr * b_dur), endpoint=False)
                atk   = int(0.015 * sr)
                env1  = np.empty_like(t_b)
                env1[:atk] = np.linspace(0, 0.45, atk)
                env1[atk:] = 0.45 * np.exp(-(t_b[atk:] - t_b[atk]) / 0.28)
                bell  = np.sin(2 * np.pi * 1400 * t_b) * env1
                bell += np.sin(2 * np.pi * 2300 * t_b) * 0.18 * np.exp(-t_b / 0.14)

                # クリック開始から 25ms 後にベルを重ねる
                delay = int(0.025 * sr)
                total = max(len(click), delay + len(bell))
                out   = np.zeros(total, dtype=np.float64)
                out[:len(click)] += click
                out[delay:delay + len(bell)] += bell
                out = np.clip(out, -1, 1).astype(np.float32)

                sd.play(out, sr); sd.wait()
            except Exception:
                pass
        _play_async(_play)
    else:
        def _fallback():
            try:
                subprocess.run(
                    ['beep', '-f', '800', '-l', '60', '-n', '-f', '1400', '-l', '420'],
                    capture_output=True, timeout=2)
            except Exception:
                sys.stdout.write('\a'); sys.stdout.flush()
        _play_async(_fallback)


# ============================================================
# 表示ヘルパー
# ============================================================

def clear():
    os.system("clear" if os.name != "nt" else "cls")


def rule(ch="="):
    print(ch * W)


def header():
    rule()
    print("         テンキーレジシステム")
    rule()


def wlen(s):
    """日本語全角文字を2文字としてカウントした表示幅を返す"""
    w = 0
    for c in s:
        w += 2 if ord(c) > 0x7F else 1
    return w


def wljust(s, width):
    """日本語対応の左揃えパディング"""
    pad = width - wlen(s)
    return s + " " * max(pad, 0)


def wrjust(s, width):
    """日本語対応の右揃えパディング"""
    pad = width - wlen(s)
    return " " * max(pad, 0) + s


def show_cart(cart, msg=""):
    """カート内容を整形して表示する"""
    # 列幅定義（表示幅）: No=3, name=18, qty=4, price=6, subtotal=7
    # 行合計: 2 + 3 + 2 + 18 + 2 + 4 + 2 + 6 + 2 + 7 = 48 display cols
    NAME_W = 18

    # ヘッダー行（全角対応の手動パディング）
    header_row = (
        "  "
        + wrjust("No", 3) + "  "
        + wljust("商品名", NAME_W) + "  "
        + wrjust("数量", 4) + "  "
        + wrjust("単価", 6) + "  "
        + wrjust("小計", 7)
    )
    print(header_row)
    rule("-")
    if not cart:
        print(f"  {'( 商品未登録 )':^46}")
    else:
        for i, (code, name, qty, price, subtotal) in enumerate(cart, 1):
            row = (
                "  "
                + wrjust(str(i), 3) + "  "
                + wljust(name, NAME_W) + "  "
                + wrjust(str(qty), 4) + "  "
                + wrjust(f"{price:,}", 6) + "  "
                + wrjust(f"{subtotal:,}", 7)
            )
            print(row)
    rule("-")
    total = sum(item[4] for item in cart)
    # 合計行: "  " + filler(36) + "  ¥" + total(7) = 48 display
    total_row = "  " + wljust("合計", 36) + "  ¥" + wrjust(f"{total:,}", 7)
    print(total_row)
    rule()
    if msg:
        print(f"  {msg}")
        rule()


def show_product_list():
    """登録商品一覧を画面表示する"""
    clear()
    rule()
    print("  登録商品一覧")
    rule("-")
    for code, (name, price) in sorted(PRODUCTS.items()):
        name_col = wljust(name, 16)
        print(f"  [{code}]  {name_col}  ¥{price:,}")
    rule()
    ask("[Enter] で戻る > ")


def ask(prompt):
    """入力プロンプト。Ctrl+C / EOF で安全に終了する"""
    try:
        return input(f"  {prompt}").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\n  システムを終了します。")
        sys.exit(0)


# ============================================================
# メイン処理
# ============================================================

def register_phase():
    """
    商品登録フェーズ。
    00 が入力されカートに商品が1件以上あれば cart を返す。
    """
    cart = []
    msg = ""

    while True:
        clear()
        header()
        show_cart(cart, msg)
        msg = ""

        print("  商品コード(2桁)+[Enter]  商品追加")
        print("  [00]=会計  [-]=直前削除  [+]=数量変更  [/]=商品一覧  [99]=終了")
        rule()

        code = ask("商品コード >> ")

        # --- 特殊コマンド ---
        if code == "99":
            clear()
            print("\n  ご利用ありがとうございました。\n")
            sys.exit(0)

        if code in ("/", "98"):
            show_product_list()
            continue

        if code == "-":
            if not cart:
                msg = "!! カートに商品がありません"
            else:
                removed = cart.pop()
                msg = f">> [{removed[0]}] {removed[1]} をカートから削除しました"
            continue

        if code == "+":
            if not cart:
                msg = "!! カートに商品がありません"
                continue
            last_code, last_name, last_qty, last_price, _ = cart[-1]
            clear()
            header()
            show_cart(cart)
            print(f"  数量変更: [{last_code}] {wljust(last_name, 14)}  現在: {last_qty} 個")
            rule()
            qty_str = ask("新しい数量 >> ")
            try:
                qty = int(qty_str)
                if not (1 <= qty <= 999):
                    raise ValueError
            except ValueError:
                msg = "!! 数量は 1〜999 の整数で入力してください"
                continue
            cart[-1] = (last_code, last_name, qty, last_price, qty * last_price)
            msg = f">> {last_name} の数量を {last_qty}個 → {qty}個 に変更しました"
            continue

        if code == "00":
            if not cart:
                msg = "!! 商品が登録されていません"
            else:
                return cart  # 会計フェーズへ
            continue

        # --- バリデーション ---
        if not (len(code) == 2 and code.isdigit()):
            msg = f"!! [{code}]  2桁の商品コードを入力してください"
            continue

        if code not in PRODUCTS:
            msg = f"!! [{code}]  登録されていない商品コードです"
            continue

        # --- 数量入力 ---
        name, price = PRODUCTS[code]

        clear()
        header()
        show_cart(cart)
        print(f"  選択商品: [{code}] {wljust(name, 14)}  ¥{price:,} / 個")
        rule()

        qty_str = ask("数量 >> [Enter]=1個  ")

        try:
            qty = int(qty_str) if qty_str else 1
            if not (1 <= qty <= 999):
                raise ValueError
        except ValueError:
            msg = "!! 数量は 1〜999 の整数で入力してください"
            continue

        subtotal = qty * price
        cart.append((code, name, qty, price, subtotal))
        play_beep()
        msg = f">> {name} x {qty}個 = ¥{subtotal:,}  登録しました"


def checkout_phase(cart):
    """
    会計フェーズ。お預かり金額を入力しお釣りを表示する。
    """
    total = sum(item[4] for item in cart)
    pay_msg = ""

    while True:
        clear()
        header()
        show_cart(cart)
        print(f"  *** お会計 ***  合計: ¥{total:,}")
        rule()
        if pay_msg:
            print(f"  {pay_msg}")
            rule()

        pay_str = ask("お預かり金額 >> ¥")

        try:
            payment = int(pay_str)
            if payment <= 0:
                raise ValueError
        except ValueError:
            pay_msg = "!! 正しい金額を入力してください"
            continue

        if payment < total:
            pay_msg = f"!! ¥{total - payment:,} 不足しています"
            continue

        break

    play_drawer()
    # --- 完了画面 ---
    change = payment - total
    clear()
    header()
    show_cart(cart)
    rule("*")
    print(f"  合計金額  :  ¥{total:>10,}")
    print(f"  お預かり  :  ¥{payment:>10,}")
    print(f"  お 釣 り  :  ¥{change:>10,}")
    rule("*")
    if change == 0:
        print("  ちょうどいただきました。ありがとうございます！")
    else:
        print(f"  ¥{change:,} をお返しします。ありがとうございます！")
    rule()
    ask("[Enter] で次のお客様へ > ")


def main():
    customer_no = 0
    while True:
        customer_no += 1
        cart = register_phase()
        checkout_phase(cart)


if __name__ == "__main__":
    main()
