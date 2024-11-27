import logging
import os
from pathlib import Path
import sqlite3
from typing import List, Dict, Any, Optional, Tuple, Union

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(name)s | %(levelname)s: %(message)s")

class SQLiteMixin:
    """
    A mixin class providing common SQLite database operations.
    Subclasses should set the DATABASE_PATH class attribute.
    """
    DATABASE_PATH: str = None

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create and return a database connection.

        Returns:
            sqlite3.Connection: An active database connection

        Raises:
            ValueError: If DATABASE_PATH is not set
        """
        if not self.DATABASE_PATH:
            raise ValueError("DATABASE_PATH must be set in the subclass")
        
        try:
            db_dir = os.path.dirname(self.DATABASE_PATH)
            if db_dir:
                Path(db_dir).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created database directory: {db_dir}")

            conn = sqlite3.connect(self.DATABASE_PATH)
            logger.debug("Database connection established.")
            return conn
        except sqlite3.Error as e:
            logger.exception(f"Error connecting to the database: {e}")
            raise

    def __execute_query(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> sqlite3.Cursor:
        """
        Helper method to execute a query and return a cursor.
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            logger.debug(f"Executed query: {query} | Params: {params}")
            return cursor
        except sqlite3.Error as e:
            logger.exception(f"Error executing query: {query} | Error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    def create_table(self, table_name: str, columns: Dict[str, str]) -> None:
        """
        Create a table with specified columns if it doesn't exist.

        Args:
            table_name (str): Name of the table to create
            columns (Dict[str, str]): Column definitions {column_name: column_type}
        """
        column_parts = []
        for col, dtype in columns.items():
            formatted_column = f"{col} {dtype}"
            column_parts.append(formatted_column)

        column_definitions = ', '.join(column_parts)

        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({column_definitions})"
        self.__execute_query(query)

    def insert(self, table_name: str, data: Dict[str, Any]) -> int:
        """
        Insert a single record into the specified table.

        Args:
            table_name (str): Name of the table
            data (Dict[str, Any]): Column names and values to insert

        Returns:
            int: ID of the last inserted row
        """
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        values = tuple(data.values())

        query = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

        cursor = self.__execute_query(query, values)
        return cursor.lastrowid

    def bulk_insert(self, table_name: str,
                    data: List[Dict[str, Any]],
                    on_duplicates) -> bool:
        """
        Insert multiple records into the specified table.

        Args:
            table_name (str): Name of the table
            data (List[Dict[str, Any]]): List of records to insert
            on_duplicates (str): The conflict resolution strategy to handle duplicate rows during inserts.

        Returns:
            bool: True if insert was successful, False otherwise
        """
        if not data:
            return False

        columns = ', '.join(data[0].keys())
        placeholders = ', '.join(['?'] * len(data[0]))
        query = f"INSERT OR {on_duplicates} INTO {table_name} ({columns}) VALUES ({placeholders})"

        try:
            values_list = []
            for record in data:
                values_list.append(tuple(record.values()))

            with self._get_connection() as conn:
                conn.executemany(query, values_list)
                conn.commit()
                logger.debug(f"Bulk inserted {len(data)} records into {table_name}.")
                return True
        except sqlite3.Error as e:
            logger.exception(f"Error in bulk insert: {e}")
            return False

    def select(self,
               table_name: str,
               columns: Optional[List[str]] = None,
               where: Optional[str] = None,
               params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        """
        Select records from the specified table.

        Args:
            table_name (str): Name of the table
            columns (Optional[List[str]]): Columns to retrieve (default: all)
            where (Optional[str]): WHERE clause for filtering
            params (Optional[tuple]): Parameters for the WHERE clause

        Returns:
            List[Dict[str, Any]]: Retrieved records
        """
        # Default to all columns if not specified
        if not columns:
            select_columns = '*'
        else:
            select_columns = ', '.join(columns)

        query = f"SELECT {select_columns} FROM {table_name}"
        if where:
            query += f" WHERE {where}"

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(query, params or ())
                rows = []
                for row in cursor.fetchall():
                    rows.append(dict(row))
                logger.debug(f"Selected {len(rows)} records from {table_name}.")
                return rows
            except sqlite3.Error as e:
                logger.error(f"Error in select query: {e}")
                raise

    def count(self,
              table_name: str,
              column: str = '*',
              distinct: bool = False,
              where: Optional[str] = None,
              params: Optional[tuple] = None,
              group_by: Optional[Union[str, List[str]]] = None) -> Union[int, List[Dict[str, Any]]]:
        """
        Count records in the specified table with optional filtering and grouping.

        Args:
            table_name (str): Name of the table
            column (str): Column to count (default: '*' for all)
            distinct (bool): Whether to count distinct values only
            where (Optional[str]): WHERE clause for filtering
            params (Optional[tuple]): Parameters for the WHERE clause
            group_by (Optional[Union[str, List[str]]]): Column(s) to group by

        Returns:
            Union[int, List[Dict[str, Any]]]: Count of records or list of counts per group

        Examples:
            # Count all records
            count = Database.count('users')

            # Count distinct values in a column
            distinct_count = Database.count('users', column='status', distinct=True)

            # Count with condition
            active_count = Database.count('users', where='status = ?', params=('active',))

            # Count grouped by status
            status_counts = Database.count('users', group_by='status')
        """
        count_expr = f"COUNT({'DISTINCT ' if distinct else ''}{column})"

        if isinstance(group_by, list):
            group_by = ', '.join(group_by)

        if group_by:
            query = f"SELECT {group_by}, {count_expr} as count FROM {table_name}"
        else:
            query = f"SELECT {count_expr} as count FROM {table_name}"

        if where:
            query += f" WHERE {where}"

        if group_by:
            query += f" GROUP BY {group_by}"

        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            if group_by:
                result = []
                for row in cursor.fetchall():
                    result.append(dict(row))
                return result
            else:
                return cursor.fetchone()['count']


    def update(self,
               table_name: str,
               data: Dict[str, Any],
               where: str,
               params: tuple) -> int:
        """
        Update records in the specified table.

        Args:
            table_name (str): Name of the table
            data (Dict[str, Any]): Columns and values to update
            where (str): WHERE clause for filtering
            params (tuple): Parameters for the WHERE clause

        Returns:
            int: Number of rows affected
        """
        set_clause_parts = []
        update_values = []

        for key, value in data.items():
            if isinstance(value, str) and value.upper() == "CURRENT_TIMESTAMP":
                set_clause_parts.append(f"{key} = CURRENT_TIMESTAMP")
            else:
                set_clause_parts.append(f"{key} = ?")
                update_values.append(value)

        set_clause = ', '.join(set_clause_parts)
        query = f"UPDATE {table_name} SET {set_clause} WHERE {where}"
        update_params = tuple(update_values) + params

        cursor = self.__execute_query(query, update_params)
        return cursor.rowcount

    def delete(self, table_name: str, where: str, params: tuple) -> int:
        """
        Delete records from the specified table.

        Args:
            table_name (str): Name of the table
            where (str): WHERE clause for filtering
            params (tuple): Parameters for the WHERE clause

        Returns:
            int: Number of rows deleted
        """
        query = f"DELETE FROM {table_name} WHERE {where}"
        cursor = self.__execute_query(query, params)
        return cursor.rowcount
