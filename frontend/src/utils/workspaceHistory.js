export function initialHistory(value) {
  return { value, saved: JSON.stringify(value), past: [], future: [] };
}
export function workspaceHistory(state, action) {
  if (action.type === 'reset') return initialHistory(action.value);
  if (action.type === 'checkpoint') return initialHistory(state.value);
  if (action.type === 'saved') return { ...state, saved: JSON.stringify(action.value) };
  if (action.type === 'undo') {
    if (!state.past.length) return state;
    return { ...state, value: state.past.at(-1), past: state.past.slice(0,-1), future: [state.value, ...state.future] };
  }
  if (action.type === 'redo') {
    if (!state.future.length) return state;
    return { ...state, value: state.future[0], past: [...state.past, state.value].slice(-50), future: state.future.slice(1) };
  }
  if (action.type === 'set') {
    const next = typeof action.value === 'function' ? action.value(state.value[action.key]) : action.value;
    if (JSON.stringify(next) === JSON.stringify(state.value[action.key])) return state;
    return { ...state, value: { ...state.value, [action.key]: next }, past: [...state.past, state.value].slice(-50), future: [] };
  }
  return state;
}
