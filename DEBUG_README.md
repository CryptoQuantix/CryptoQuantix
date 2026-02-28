# Debug Logging & Testing - Quick Reference

## 🚀 Quick Start

### 1. Update Configuration
```bash
# Run the update script (already done)
.\update-env.bat
```

### 2. Restart Bot
```bash
docker-compose restart
```

### 3. View Enhanced Logs
```bash
docker-compose logs -f coinmaker-bot
```

## 🧪 Test Components

```bash
# Test Smart Money components
python scripts\test_smart_money.py
```

## 📊 What to Expect

### Normal Behavior (No Signals)
- ✓ Bot scans every 5 minutes
- ✓ Most scans: "Outside trading window" (14:00-17:00 only)
- ✓ Inside window: "No liquidity sweep detected" (normal)
- ✓ Sweep found: "No Absorption confirmation" (needs both)

### Signal Generated (Rare!)
```
INFO - >>> CONFLUENCE: Bullish Sweep + Bullish Absorption <<<
INFO - Executing Smart Money buy on BTC-PERPETUAL
```

## 🔧 Adjust Sensitivity (Optional)

Edit `.env`:
```bash
# More sensitive (more signals, lower quality)
SM_ABSORPTION_MIN_VOL=5.0
SM_ABSORPTION_DELTA_RATIO=0.10

# Less sensitive (fewer signals, higher quality)
SM_ABSORPTION_MIN_VOL=15.0
SM_ABSORPTION_DELTA_RATIO=0.20
```

## 📁 New Files

- `src/utils/metrics.py` - Performance tracking
- `scripts/test_smart_money.py` - Component testing
- `update-env.bat/sh` - Config updater
- `DEBUG_LOGGING_GUIDE.md` - Full documentation

## ✅ Verification Checklist

- [ ] `.env` has `LOG_LEVEL=DEBUG`
- [ ] Bot restarted after config change
- [ ] Logs show DEBUG messages
- [ ] Test script runs successfully

---
For detailed documentation, see `DEBUG_LOGGING_GUIDE.md`
