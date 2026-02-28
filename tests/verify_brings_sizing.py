
def calculate_size(qty_btc, entry_price, symbol):
    is_inverse = "PERPETUAL" in symbol and "USDC" not in symbol
    size = 0.0
    if is_inverse:
            if "BTC" in symbol: contract_val = 10.0 
            else: contract_val = 1.0
            
            qty_usd_raw = qty_btc * entry_price
            # Deribit 'amount' for Inverse is in USD, but must be multiple of contract_val.
            # We must send USD amount (e.g. 18620), NOT number of contracts.
            steps = int(qty_usd_raw / contract_val)
            size = steps * int(contract_val)
    else:
            # Linear
            size = round(qty_btc, 4)
    return size

print("--- BTC Test ---")
qty_btc = 2.055
entry_price = 90604.98
symbol = "BTC-PERPETUAL"
size = calculate_size(qty_btc, entry_price, symbol)
print(f"Qty BTC: {qty_btc}, Price: {entry_price}")
print(f"Calculated Size: {size}")
if size % 10 == 0:
    print("PASS: Size is multiple of 10")
else:
    print("FAIL: Size is NOT multiple of 10")

print("\n--- ETH Test ---")
qty_btc = 20.5 # Qty ETH actually
entry_price = 3000.00
symbol = "ETH-PERPETUAL"
size = calculate_size(qty_btc, entry_price, symbol)
print(f"Qty ETH: {qty_btc}, Price: {entry_price}")
print(f"Calculated Size: {size}")
if size % 1 == 0: # Check if integer
    print("PASS: Size is Integer")
else:
    print("FAIL: Size is NOT Integer") 

def round_sl(price, symbol):
    tick_size = 0.5 if "BTC" in symbol else 0.05
    return round(price / tick_size) * tick_size

print("\n--- SL Rounding Test ---")
symbol = "BTC-PERPETUAL"
raw_sl = 90848.24
rounded = round_sl(raw_sl, symbol)
print(f"Raw: {raw_sl}, Rounded: {rounded}")
# Check if close to multiple of 0.5 (using epsilon for float)
rem = rounded % 0.5
if rem < 1e-9 or abs(rem - 0.5) < 1e-9:
    print("PASS: Multiple of 0.5")
else:
    print(f"FAIL: Remainder {rem}")
