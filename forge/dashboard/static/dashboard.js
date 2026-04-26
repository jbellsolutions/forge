// forge dashboard — minimal client. HTMX handles most interactivity.
// Add behaviors here only when HTMX can't reach.

document.addEventListener('htmx:afterRequest', (evt) => {
  // After Approve/Reject on a pending action: reload to update the list.
  if (evt.detail.target?.matches?.('button[hx-post*="/actions/"]')) {
    setTimeout(() => location.reload(), 250);
  }
});

// Auto-scroll the chat log on new messages.
document.addEventListener('htmx:afterSwap', (evt) => {
  const log = document.getElementById('chat-log');
  if (log && evt.detail.target?.id === 'chat-log') {
    log.scrollTop = log.scrollHeight;
  }
});
