from fastmcp import FastMCP
import os
import aiosqlite
from datetime import datetime, timedelta
import json
import re
from typing import Dict, List, Tuple, Optional
import asyncio
import aiofiles

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")
CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), "categories.json")

mcp = FastMCP("ExpenseTracker")


async def load_categories() -> Dict:
    """Load categories and subcategories from JSON file asynchronously."""
    try:
        async with aiofiles.open(CATEGORIES_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        # Create default categories file if it doesn't exist
        default_categories = {
            "categories": {
                "Food & Dining": {"subcategories": ["Groceries", "Restaurants", "Takeout", "Coffee"]},
                "Transportation": {"subcategories": ["Fuel", "Public Transport", "Taxi"]},
                "Other": {"subcategories": ["Miscellaneous"]}
            }
        }
        async with aiofiles.open(CATEGORIES_FILE, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(default_categories, indent=2))
        return default_categories
    except Exception as e:
        print(f"Error loading categories: {e}")
        return {"categories": {}}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT "",
                note TEXT DEFAULT "",
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


# Initialize database asynchronously
asyncio.create_task(init_db())


class CategoryManager:
    def __init__(self):
        self.categories_data = asyncio.create_task(load_categories())
        self.categories = asyncio.run(asyncio.create_task(self.categories_data))  # Wait for load
        self._build_category_mappings()

    def _build_category_mappings(self):
        """Build mappings for quick category/subcategory lookups."""
        self.category_names = list(self.categories.keys())
        self.subcategory_mapping = {}
        self.keyword_mappings = self._build_keyword_mappings()

        for category, data in self.categories.items():
            subcategories = data.get("subcategories", [])
            for subcat in subcategories:
                self.subcategory_mapping[subcat.lower()] = category

    def _build_keyword_mappings(self) -> Dict[str, str]:
        """Build keyword to category mappings for auto-detection."""
        mappings = {
            # Food & Dining
            "food|grocery|supermarket|market|vegetable|fruit|meat|bread": "Food & Dining",
            "restaurant|cafe|diner|eatery|buffet|steakhouse|pizzeria": "Food & Dining",
            "coffee|tea|starbucks|costa|espresso|latte": "Food & Dining",
            "takeout|delivery|doordash|ubereats|grubhub": "Food & Dining",
            "alcohol|beer|wine|liquor|bar|pub|brewery": "Food & Dining",

            # Transportation
            "fuel|gas|petrol|diesel|gas station": "Transportation",
            "bus|train|subway|metro|transit|rail": "Transportation",
            "taxi|uber|lyft|ride share|cab": "Transportation",
            "parking|garage|valet": "Transportation",
            "toll|highway|road fee": "Transportation",
            "car wash|maintenance|repair|mechanic|oil change|tire": "Transportation",
            "flight|airline|airport|plane": "Transportation",

            # Housing
            "rent|lease|apartment|house": "Housing",
            "mortgage|loan payment": "Housing",
            "electricity|power|energy": "Housing",
            "water|sewer|utility": "Housing",
            "internet|wifi|broadband": "Housing",
            "gas|heating|propane": "Housing",
            "trash|garbage|waste": "Housing",

            # Shopping
            "clothing|shoes|apparel|fashion": "Shopping",
            "electronics|computer|laptop|phone|tablet": "Shopping",
            "amazon|ebay|walmart|target|online shopping": "Shopping",
            "gift|present|donation": "Gifts & Donations",

            # Healthcare
            "doctor|hospital|clinic|medical": "Healthcare",
            "pharmacy|drugstore|medicine|prescription": "Healthcare",
            "dentist|dental|teeth": "Healthcare",
            "optometrist|glasses|contact lens": "Healthcare",
            "gym|fitness|yoga|exercise": "Healthcare",

            # Entertainment
            "movie|cinema|theater": "Entertainment",
            "netflix|spotify|hulu|disney|streaming": "Entertainment",
            "concert|show|performance": "Entertainment",
            "game|gaming|playstation|xbox|nintendo": "Entertainment",

            # Bills
            "phone|mobile|cellular|verizon|at&t": "Bills & Utilities",
            "cable|tv|television": "Bills & Utilities",
            "insurance|premium": "Insurance",

            # Income
            "salary|paycheck|income|wage": "Income",
            "bonus|commission": "Income",
            "refund|rebate": "Income",
        }

        keyword_to_category = {}
        for pattern, category in mappings.items():
            keywords = pattern.split("|")
            for keyword in keywords:
                keyword_to_category[keyword] = category
        return keyword_to_category

    def get_all_categories(self) -> List[str]:
        """Get all available categories."""
        return self.category_names

    def get_subcategories(self, category: str) -> List[str]:
        """Get all subcategories for a given category."""
        return self.categories.get(category, {}).get("subcategories", [])

    def validate_category(self, category: str) -> bool:
        """Check if category exists."""
        return category in self.categories

    def validate_subcategory(self, category: str, subcategory: str) -> bool:
        """Check if subcategory exists for given category."""
        if subcategory == "":
            return True
        return subcategory in self.get_subcategories(category)

    def auto_detect_category(self, note: str, amount: float) -> Tuple[str, str]:
        """Auto-detect category and subcategory based on note content."""
        note_lower = note.lower()

        # Check for exact subcategory matches first
        for subcat, category in self.subcategory_mapping.items():
            if subcat in note_lower:
                return category, subcat.capitalize()

        # Check keyword mappings
        for keyword, category in self.keyword_mappings.items():
            if keyword in note_lower:
                subcategories = self.get_subcategories(category)
                if subcategories:
                    return category, subcategories[0]  # Return first subcategory as default

        # Amount-based detection for income
        if amount < 0:  # Negative amount typically indicates income
            return "Income", "Salary"

        # Default fallback
        return "Other", "Miscellaneous"

    def suggest_categories(self, note: str) -> List[Tuple[str, str]]:
        """Suggest possible categories and subcategories based on note."""
        suggestions = []
        note_lower = note.lower()

        for category, data in self.categories.items():
            subcategories = data.get("subcategories", [])
            for subcat in subcategories:
                if subcat.lower() in note_lower:
                    suggestions.append((category, subcat))

        # If no direct matches, use keyword detection
        if not suggestions:
            detected_category, detected_subcategory = self.auto_detect_category(note, 0)
            suggestions.append((detected_category, detected_subcategory))

        return suggestions[:3]  # Return top 3 suggestions


# Initialize category manager
category_manager = CategoryManager()


@mcp.tool()
async def add_expense(date: str, amount: float, category: str = "", subcategory: str = "", note: str = ""):
    '''Add a new expense entry to the database with category validation.'''
    try:
        # Auto-detect category if not provided
        if not category:
            category, detected_subcategory = category_manager.auto_detect_category(note, amount)
            if not subcategory:
                subcategory = detected_subcategory

        # Validate category
        if not category_manager.validate_category(category):
            suggestions = category_manager.suggest_categories(note)
            suggestion_text = ", ".join([f"{cat} ({sub})" for cat, sub in suggestions])
            return {
                'status': "error",
                'message': f"Invalid category '{category}'. Did you mean: {suggestion_text}?",
                'suggestions': suggestions
            }

        # Validate subcategory
        if subcategory and not category_manager.validate_subcategory(category, subcategory):
            valid_subcategories = category_manager.get_subcategories(category)
            return {
                'status': "error",
                'message': f"Invalid subcategory '{subcategory}' for category '{category}'. Valid subcategories: {', '.join(valid_subcategories)}",
                'valid_subcategories': valid_subcategories
            }

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?,?,?,?,?)",
                (date, amount, category, subcategory, note)
            )
            await db.commit()
            cursor = await db.execute("SELECT last_insert_rowid()")
            rowid = (await cursor.fetchone())[0]
            return {
                'status': "success",
                "id": rowid,
                "message": "Expense added successfully",
                "category": category,
                "subcategory": subcategory
            }
    except Exception as e:
        return {'status': "error", "message": f"Failed to add expense: {str(e)}"}


@mcp.tool()
async def suggest_categories(note: str):
    '''Suggest possible categories and subcategories based on the note.'''
    try:
        suggestions = category_manager.suggest_categories(note)
        return {
            'status': 'success',
            'suggestions': [{'category': cat, 'subcategory': sub} for cat, sub in suggestions]
        }
    except Exception as e:
        return {'status': 'error', 'message': f'Failed to suggest categories: {str(e)}'}


@mcp.tool()
async def get_categories():
    '''Get all available categories and their subcategories.'''
    try:
        categories = {}
        for category in category_manager.get_all_categories():
            categories[category] = category_manager.get_subcategories(category)
        return {
            'status': 'success',
            'categories': categories
        }
    except Exception as e:
        return {'status': 'error', 'message': f'Failed to get categories: {str(e)}'}


@mcp.tool()
async def list_expenses(limit: int = 100, offset: int = 0):
    '''List all expenses with pagination.'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, amount, category, subcategory, note, created_at FROM expenses ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ) as cursor:
            cols = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()
            expenses = [dict(zip(cols, row)) for row in rows]
            return expenses


@mcp.tool()
async def update_expense(expense_id: int, date: str = None, amount: float = None, category: str = None, subcategory: str = None, note: str = None):
    '''Update an existing expense entry.'''
    try:
        updates = []
        params = []

        if date is not None:
            updates.append("date = ?")
            params.append(date)
        if amount is not None:
            updates.append("amount = ?")
            params.append(amount)
        if category is not None:
            # Validate new category
            if not category_manager.validate_category(category):
                return {'status': "error", "message": f"Invalid category '{category}'"}
            updates.append("category = ?")
            params.append(category)
        if subcategory is not None:
            # Validate subcategory against category
            current_category = category
            if current_category is None:
                # Get current category from database
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute("SELECT category FROM expenses WHERE id = ?", (expense_id,)) as cursor:
                        result = await cursor.fetchone()
                        if result:
                            current_category = result[0]

            if current_category and not category_manager.validate_subcategory(current_category, subcategory):
                return {'status': "error", "message": f"Invalid subcategory '{subcategory}' for category '{current_category}'"}

            updates.append("subcategory = ?")
            params.append(subcategory)
        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if not updates:
            return {'status': "error", "message": "No fields to update"}

        params.append(expense_id)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE expenses SET {', '.join(updates)} WHERE id = ?",
                params
            )
            await db.commit()

            # Check if update affected any rows
            async with db.execute("SELECT changes()") as cursor:
                changes = (await cursor.fetchone())[0]
                if changes > 0:
                    return {'status': "success", "message": "Expense updated successfully"}
                else:
                    return {'status': "error", "message": "Expense not found"}

    except Exception as e:
        return {'status': "error", "message": f"Failed to update expense: {str(e)}"}


@mcp.tool()
async def delete_expense(expense_id: int):
    '''Delete an expense entry by ID.'''
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
            await db.commit()

            # Check if deletion affected any rows
            async with db.execute("SELECT changes()") as cursor:
                changes = (await cursor.fetchone())[0]
                if changes > 0:
                    return {'status': "success", "message": "Expense deleted successfully"}
                else:
                    return {'status': "error", "message": "Expense not found"}

    except Exception as e:
        return {'status': "error", "message": f"Failed to delete expense: {str(e)}"}


@mcp.tool()
async def get_expense_by_id(expense_id: int):
    '''Get a specific expense by ID.'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, amount, category, subcategory, note, created_at FROM expenses WHERE id = ?",
            (expense_id,)
        ) as cursor:
            cols = [description[0] for description in cursor.description]
            row = await cursor.fetchone()

            if row:
                return dict(zip(cols, row))
            else:
                return {'status': "error", "message": "Expense not found"}


@mcp.tool()
async def get_expenses_by_category(category: str):
    '''Get all expenses for a specific category.'''
    if not category_manager.validate_category(category):
        return {'status': "error", "message": f"Invalid category '{category}'"}

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, amount, category, subcategory, note, created_at FROM expenses WHERE category = ? ORDER BY date DESC",
            (category,)
        ) as cursor:
            cols = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()
            expenses = [dict(zip(cols, row)) for row in rows]
            return expenses


@mcp.tool()
async def get_expenses_by_date_range(start_date: str, end_date: str):
    '''Get expenses within a date range (inclusive).'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, amount, category, subcategory, note, created_at FROM expenses WHERE date BETWEEN ? AND ? ORDER BY date DESC",
            (start_date, end_date)
        ) as cursor:
            cols = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()
            expenses = [dict(zip(cols, row)) for row in rows]
            return expenses


@mcp.tool()
async def get_expense_summary(period: str = "month"):
    '''Get expense summary by period (month, week, year).'''
    async with aiosqlite.connect(DB_PATH) as db:
        if period == "month":
            query = """
                SELECT strftime('%Y-%m', date) as period,
                       category,
                       SUM(amount) as total
                FROM expenses
                GROUP BY period, category
                ORDER BY period DESC, total DESC
            """
        elif period == "week":
            query = """
                SELECT strftime('%Y-%W', date) as period,
                       category,
                       SUM(amount) as total
                FROM expenses
                GROUP BY period, category
                ORDER BY period DESC, total DESC
            """
        elif period == "year":
            query = """
                SELECT strftime('%Y', date) as period,
                       category,
                       SUM(amount) as total
                FROM expenses
                GROUP BY period, category
                ORDER BY period DESC, total DESC
            """
        else:
            return {'status': "error", "message": "Invalid period. Use 'month', 'week', or 'year'"}

        async with db.execute(query) as cursor:
            cols = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()
            summary = [dict(zip(cols, row)) for row in rows]
            return summary


@mcp.tool()
async def get_total_spending():
    '''Get total spending across all expenses.'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT SUM(amount) as total_spent FROM expenses") as cursor:
            row = await cursor.fetchone()
            return {'total_spent': row[0] if row[0] is not None else 0}


@mcp.tool()
async def search_expenses(query: str):
    '''Search expenses by note or category.'''
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, date, amount, category, subcategory, note, created_at FROM expenses WHERE note LIKE ? OR category LIKE ? ORDER BY date DESC",
            (f'%{query}%', f'%{query}%')
        ) as cursor:
            cols = [description[0] for description in cursor.description]
            rows = await cursor.fetchall()
            expenses = [dict(zip(cols, row)) for row in rows]
            return expenses


@mcp.tool()
async def get_recent_expenses(days: int = 7):
    '''Get expenses from the last N days.'''
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    return await get_expenses_by_date_range(start_date, end_date)


@mcp.tool()
async def export_expenses(format_type: str = 'json'):
    '''Export all expenses in specified format (currently only JSON).'''
    try:
        expenses = await list_expenses(limit=10000)  # Large limit to get all expenses

        if format_type.lower() == 'json':
            return {
                'status': 'success',
                'format': 'json',
                'data': expenses,
                'count': len(expenses),
                'exported_at': datetime.now().isoformat()
            }
        else:
            return {'status': 'error', 'message': 'Unsupported format. Use "json"'}

    except Exception as e:
        return {'status': 'error', 'message': f'Export failed: {str(e)}'}


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)