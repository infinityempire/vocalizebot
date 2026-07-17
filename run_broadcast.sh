#!/bin/bash
# =============================================================================
# VocalizeBot - סקריפט הפצה
# =============================================================================
# שימוש: bash run_broadcast.sh <הודעה> [premium|free|all]
# =============================================================================

set -e

# טען משתני סביבה
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# בדוק שיש BOT TOKEN
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ שגיאה: TELEGRAM_BOT_TOKEN לא מוגדר ב-.env"
    exit 1
fi

# הודעה ברירת מחדל
MESSAGE="${1:-🎙️ VocalizeBot - שלום! הבוט מוכן לתמלולים חינם!}"
FILTER="${2:-all}"

echo "📤 מתחיל הפצה..."
echo "   הודעה: $MESSAGE"
echo "   מסנן: $FILTER"
echo ""

python3 broadcast.py "$MESSAGE" --filter=$FILTER --delay=1
