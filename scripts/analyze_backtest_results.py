import pandas as pd

def analyze():
    try:
        df = pd.read_csv("data/backtest/wm_backtest_trades.csv")
    except FileNotFoundError:
        print("No trades file found.")
        return

    total_trades = len(df)
    wins = len(df[df['pnl'] > 0])
    losses = len(df[df['pnl'] <= 0])
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    
    initial_capital = 10000
    total_pnl = df['pnl'].sum()
    final_capital = initial_capital + total_pnl
    return_pct = (total_pnl / initial_capital) * 100
    
    avg_win = df[df['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
    avg_loss = df[df['pnl'] <= 0]['pnl'].mean() if losses > 0 else 0
    
    print("="*40)
    print("BACKTEST RESULTS ANALYSIS")
    print("="*40)
    print(f"Total Trades:    {total_trades}")
    print(f"Win Rate:        {win_rate:.2f}%")
    print(f"Total Return:    {return_pct:.2f}%")
    print(f"Final Capital:   ${final_capital:.2f}")
    print(f"Average Win:     ${avg_win:.2f}")
    print(f"Average Loss:    ${avg_loss:.2f}")
    print(f"Profit Factor:   {abs(df[df['pnl'] > 0]['pnl'].sum() / df[df['pnl'] <= 0]['pnl'].sum()) if losses > 0 else 'Inf':.2f}")
    print("="*40)

if __name__ == "__main__":
    analyze()
