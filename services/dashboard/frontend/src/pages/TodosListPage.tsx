/**
 * Standalone TODO list page with filters, sorting, and pagination.
 *
 * Fetches TODOs from the API with optional status, category, and epic
 * filters, supports column-header sort toggling, and provides
 * offset-based "Load more" pagination.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { fetchTodos } from '../api/client';
import type { FetchTodosParams } from '../api/client';
import { TodoItemRow } from '../components/TodoItem';
import type { TodoItem } from '../types';

/** Number of TODOs to fetch per page. */
const PAGE_SIZE = 25;

/**
 * Full-page list of TODO items with filters, sortable column headers,
 * a results count, and incremental "Load more" pagination.
 *
 * Filter state changes reset the offset and replace the current list.
 * "Load more" appends the next page to the existing list.
 *
 * @returns The TODOs list page element.
 */
export function TodosListPage(): React.JSX.Element {
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<string>(searchParams.get('status') || 'open');
  const [category, setCategory] = useState<string>(searchParams.get('category') || '');
  const [epicId, setEpicId] = useState<string>(searchParams.get('epic_id') || '');
  const [sort, setSort] = useState<string>(searchParams.get('sort') || 'priority');
  const [order, setOrder] = useState<string>(searchParams.get('order') || 'asc');

  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [total, setTotal] = useState<number>(0);
  const [hasMore, setHasMore] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState<number>(0);
  const [knownCategories, setKnownCategories] = useState<string[]>([]);

  const categoryOptions = useMemo<string[]>(() => {
    const fromPage = todos.filter((t) => t.category).map((t) => t.category!);
    return [...new Set([...knownCategories, ...fromPage])].sort();
  }, [todos, knownCategories]);

  const loadTodos = useCallback(
    async (currentOffset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const params: FetchTodosParams = {
          status: status || undefined,
          category: category || undefined,
          epic_id: epicId || undefined,
          sort,
          order,
          limit: PAGE_SIZE,
          offset: currentOffset,
        };
        const data = await fetchTodos(params);
        setTodos((prev) => (append ? [...prev, ...data.todos] : data.todos));
        setTotal(data.total);
        setHasMore(data.has_more);
        if (!category && !append) {
          const cats = data.todos.filter((t) => t.category).map((t) => t.category!);
          setKnownCategories((prev) => [...new Set([...prev, ...cats])]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load TODOs.');
      } finally {
        setLoading(false);
      }
    },
    [status, category, epicId, sort, order],
  );

  useEffect(() => {
    setOffset(0);
    void loadTodos(0, false);
  }, [loadTodos]);

  const handleLoadMore = useCallback(() => {
    const nextOffset = offset + PAGE_SIZE;
    setOffset(nextOffset);
    void loadTodos(nextOffset, true);
  }, [offset, loadTodos]);

  const handleRefresh = useCallback(() => {
    setOffset(0);
    void loadTodos(0, false);
  }, [loadTodos]);

  /**
   * Toggle sort column and direction when a column header is clicked.
   *
   * If the same column is clicked again the order is reversed;
   * otherwise the column is changed and direction resets to "asc".
   *
   * @param col - The sort column identifier.
   */
  function handleSortClick(col: string): void {
    if (sort === col) {
      setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSort(col);
      setOrder('asc');
    }
  }

  /**
   * Build the CSS class string for a sort button.
   *
   * @param col - The column this button represents.
   * @returns CSS class string including the active modifier when selected.
   */
  function sortBtnClass(col: string): string {
    return `todos-page__sort-btn${sort === col ? ' todos-page__sort-btn--active' : ''}`;
  }

  /**
   * Render the sort direction indicator for the active column.
   *
   * @param col - The column to check.
   * @returns Arrow string or empty string when the column is not active.
   */
  function sortArrow(col: string): string {
    if (sort !== col) return '';
    return order === 'asc' ? ' \u2191' : ' \u2193';
  }

  return (
    <div className="todos-page">
      <h1 className="todos-page__title">TODOs</h1>

      <div className="todos-page__filters">
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Filter by status"
        >
          <option value="open">Open</option>
          <option value="assigned">Assigned</option>
          <option value="done">Done</option>
          <option value="all">All</option>
        </select>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Filter by category"
        >
          <option value="">All categories</option>
          {categoryOptions.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>

        <input
          type="text"
          placeholder="Epic ID..."
          value={epicId}
          onChange={(e) => setEpicId(e.target.value)}
          aria-label="Filter by epic ID"
        />
      </div>

      <div className="todos-page__sort">
        <button type="button" className={sortBtnClass('priority')} onClick={() => handleSortClick('priority')}>
          Priority{sortArrow('priority')}
        </button>
        <button type="button" className={sortBtnClass('created_at')} onClick={() => handleSortClick('created_at')}>
          Created{sortArrow('created_at')}
        </button>
        <button
          type="button"
          className={sortBtnClass('last_updated_at')}
          onClick={() => handleSortClick('last_updated_at')}
        >
          Updated{sortArrow('last_updated_at')}
        </button>
      </div>

      <span className="todos-page__count">{total} result(s)</span>

      {error && <div className="error-message">{error}</div>}

      {loading && todos.length === 0 && (
        <div className="loading">Loading TODOs...</div>
      )}

      {!loading && todos.length === 0 && !error && (
        <div className="epic-list__empty">No TODOs found.</div>
      )}

      {todos.map((todo) => (
        <TodoItemRow key={todo.id} todo={todo} onUpdate={handleRefresh} />
      ))}

      {loading && todos.length > 0 && <div className="loading">Loading TODOs...</div>}

      {hasMore && !loading && (
        <button className="load-more-btn" onClick={handleLoadMore}>
          Load more
        </button>
      )}
    </div>
  );
}
