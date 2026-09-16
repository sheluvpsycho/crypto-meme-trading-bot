import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os
import requests
from typing import Optional

class UltimateTradingBot:
    def __init__(self, exchange_name: str = "kraken", api_key: str = None, 
                 api_secret: str = None, symbol: str = "DOGE/USDT", 
                 account_type: str = "paper", starting_balance: float = 1000):
        
        self.exchange_name = exchange_name.lower()
        self.symbol = symbol
        self.account_type = account_type
        
        # Telegram setup
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        
        if account_type == "paper":
            self.exchange = None
            self.paper_balance = starting_balance
            self.starting_balance = starting_balance
            print(f"✓ Paper trading initialized with ${starting_balance:.2f}")
        else:
            try:
                exchange_class = getattr(ccxt, self.exchange_name)
                self.exchange = exchange_class({
                    'apiKey': api_key or '',
                    'secret': api_secret or '',
                    'enableRateLimit': True
                })
                balance = self.exchange.fetch_balance()
                usdt_balance = balance.get('USDT', {}).get('free', 0)
                self.starting_balance = usdt_balance
                print(f"✓ Connected to {self.exchange_name}")
            except Exception as e:
                print(f"✗ Connection error: {e}")
                raise
        
        # TREND FOLLOWING (Most Important!)
        self.trend_sma_short = 20
        self.trend_sma_long = 50
        self.trend_sma_ultra = 200
        
        # RSI Settings
        self.rsi_period = 14
        self.rsi_oversold = 30
        self.rsi_overbought = 70
        
        # Support/Resistance (Precise Entry)
        self.lookback_period = 30
        
        # Volume (Real Money Filter)
        self.volume_threshold = 2.0
        
        # Risk Management (Professional)
        self.position_size = 0.85
        self.stop_loss_percent = 2.0
        self.take_profit_percent = 12.0
        self.trailing_stop_percent = 4.0
        
        self.current_position = None
        self.entry_price = None
        self.position_high = None
        self.trade_history = []
        self.daily_pnl = 0
    
    def send_telegram(self, message: str):
        if not self.telegram_token or not self.telegram_chat_id:
            return
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            requests.post(url, data={"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
        except:
            pass
    
    def calculate_trend(self, df):
        """Trend Following - Most Important Filter!"""
        if len(df) < 200:
            return 'NEUTRAL'
        
        sma_20 = df['close'].tail(20).mean()
        sma_50 = df['close'].tail(50).mean()
        sma_200 = df['close'].tail(200).mean()
        current_price = df['close'].iloc[-1]
        
        if sma_20 > sma_50 > sma_200 and current_price > sma_20:
            return 'STRONG_UP'
        elif sma_20 > sma_50 and current_price > sma_50:
            return 'UP'
        elif sma_20 < sma_50 < sma_200 and current_price < sma_20:
            return 'STRONG_DOWN'
        elif sma_20 < sma_50 and current_price < sma_50:
            return 'DOWN'
        else:
            return 'NEUTRAL'
    
    def calculate_rsi(self, prices, period: int = 14) -> Optional[float]:
        if len(prices) < period + 1:
            return None
        deltas = np.diff(prices[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100 if avg_gain > 0 else 0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def calculate_support_resistance(self, df):
        """Precision Entry Points"""
        if len(df) < 30:
            return None, None
        support = df['low'].tail(30).min()
        resistance = df['high'].tail(30).max()
        return support, resistance
    
    def calculate_volume_signal(self, df):
        """Real Money Filter"""
        if len(df) < 20:
            return False
        avg_vol = df['volume'].tail(20).mean()
        return df['volume'].iloc[-1] > (avg_vol * self.volume_threshold)
    
    def fetch_candles(self, timeframe: str = '1h', limit: int = 200):
        try:
            if self.account_type == "paper":
                temp_exchange = ccxt.kraken()
                candles = temp_exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit)
            else:
                candles = self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit)
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            return df
        except:
            return None
    
    def get_signal(self, df):
        if df is None or len(df) < 200:
            return 'HOLD'
        
        # TREND FILTER (Most Important!)
        trend = self.calculate_trend(df)
        if trend in ['STRONG_DOWN', 'DOWN']:
            return 'HOLD'  # Don't trade downtrends!
        
        rsi = self.calculate_rsi(df['close'].values)
        if rsi is None:
            return 'HOLD'
        
        support, resistance = self.calculate_support_resistance(df)
        volume_signal = self.calculate_volume_signal(df)
        current_price = df['close'].iloc[-1]
        
        # BUY SIGNAL (Multiple Confirmations!)
        if self.current_position is None and trend in ['UP', 'STRONG_UP']:
            buy_signals = 0
            
            if rsi < self.rsi_oversold:
                buy_signals += 1
            if support and current_price < support * 1.03:
                buy_signals += 1
            if volume_signal:
                buy_signals += 1
            if trend == 'STRONG_UP':
                buy_signals += 1
            
            if buy_signals >= 3:
                return 'BUY'
        
        # SELL SIGNAL
        if self.current_position is not None:
            pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
            
            if rsi > self.rsi_overbought:
                return 'SELL'
            if resistance and current_price > resistance * 0.97:
                return 'SELL'
            if pnl_pct > self.take_profit_percent:
                return 'SELL'
            if pnl_pct < -self.stop_loss_percent:
                return 'SELL'
            if self.position_high and ((self.position_high - current_price) / self.position_high) * 100 > self.trailing_stop_percent:
                return 'SELL'
        
        return 'HOLD'
    
    def execute_buy(self, current_price: float) -> bool:
        if self.current_position is not None:
            return False
        
        available = self.paper_balance if self.account_type == "paper" else self.exchange.fetch_balance()['USDT']['free']
        position_value = available * self.position_size
        
        if position_value < 10:
            return False
        
        amount = position_value / current_price
        self.current_position = {'amount': amount, 'entry_price': current_price}
        self.entry_price = current_price
        self.position_high = current_price
        self.paper_balance -= position_value
        
        msg = f"🟢 <b>ULTIMATE DOGE BUY!</b> 🐕\n\n{self.symbol}\nAmount: {amount:.2f}\nPrice: ${current_price:.4f}"
        self.send_telegram(msg)
        print(f"🟢 BUY: {amount:.2f} @ ${current_price:.4f}")
        return True
    
    def execute_sell(self, current_price: float) -> bool:
        if self.current_position is None:
            return False
        
        amount = self.current_position['amount']
        pnl = (current_price - self.entry_price) * amount
        pnl_pct = (pnl / (self.entry_price * amount)) * 100
        
        self.paper_balance += amount * current_price
        self.daily_pnl += pnl
        
        msg = f"🔴 <b>ULTIMATE DOGE SELL!</b> 🐕\n\n{self.symbol}\nSell: ${current_price:.4f}\n<b>PnL: ${pnl:.2f} ({pnl_pct:.2f}%)</b>"
        self.send_telegram(msg)
        print(f"🔴 SELL: {amount:.2f} @ ${current_price:.4f} | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")
        
        self.trade_history.append({'timestamp': datetime.now(), 'pnl': pnl})
        self.current_position = None
        self.entry_price = None
        self.position_high = None
        return True
    
    def run_loop(self, interval_seconds: int = 60):
        print(f"\n🐕 ULTIMATE DOGE BOT ACTIVATED! {self.symbol}")
        print(f"   Strategy: Trend + Support/Resistance + Volume")
        print(f"   Win Rate Target: 75-85%")
        print(f"   Profit Target: +12-15% per trade\n")
        
        try:
            while True:
                try:
                    df = self.fetch_candles('1h', limit=200)
                    if df is None:
                        time.sleep(interval_seconds)
                        continue
                    
                    current_price = df['close'].iloc[-1]
                    signal = self.get_signal(df)
                    rsi = self.calculate_rsi(df['close'].values)
                    trend = self.calculate_trend(df)
                    
                    status = f"Trend: {trend} | RSI: {rsi:.1f} | Price: ${current_price:.4f} | Signal: {signal}"
                    if self.current_position:
                        pnl_pct = ((current_price - self.entry_price) / self.entry_price) * 100
                        status += f" | PnL: {pnl_pct:.2f}%"
                    
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {status}")
                    
                    if signal == 'BUY':
                        self.execute_buy(current_price)
                    elif signal == 'SELL':
                        self.execute_sell(current_price)
                    
                    time.sleep(interval_seconds)
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"✗ Error: {e}")
                    time.sleep(interval_seconds)
        finally:
            self.print_summary()
    
    def print_summary(self):
        current_balance = self.paper_balance
        total_pnl = current_balance - self.starting_balance
        pnl_pct = (total_pnl / self.starting_balance) * 100
        
        print("\n" + "="*60)
        print("🐕 ULTIMATE DOGE BOT - SUMMARY")
        print("="*60)
        print(f"Starting: ${self.starting_balance:.2f}")
        print(f"Current: ${current_balance:.2f}")
        print(f"PnL: ${total_pnl:.2f} ({pnl_pct:.2f}%)")
        print(f"Trades: {len(self.trade_history)}")
        if self.trade_history:
            wins = len([t for t in self.trade_history if t['pnl'] > 0])
            print(f"Win Rate: {(wins/len(self.trade_history))*100:.1f}%")
        print("="*60)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    bot = UltimateTradingBot(
        exchange_name="kraken",
        api_key=os.getenv("KRAKEN_API_KEY", ""),
        api_secret=os.getenv("KRAKEN_API_SECRET", ""),
        symbol="DOGE/USDT",
        account_type=os.getenv("ACCOUNT_TYPE", "paper")
    )
    bot.run_loop(interval_seconds=60)
