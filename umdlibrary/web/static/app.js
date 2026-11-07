// Job polling. Every page keeps the "n jobs running" word in the header
// fresh; a job page and the jobs list refresh their bars and logs. The
// pages render fully without this; it only saves pressing Refresh.
(function () {
  function render(job) {
    document.querySelectorAll('[data-job="' + job.id + '"]').forEach(function (el) {
      el.className = 'job ' + job.state;
      el.querySelector('.state').textContent = job.state;
      el.querySelector('.fill').style.width = job.percent + '%';
      el.querySelector('.msg').textContent = job.message || '';
      var times = 'queued ' + job.queued_at + (job.started_at ? ', started ' + job.started_at : '') + (job.ended_at ? ', ended ' + job.ended_at : '');
      el.querySelector('.times').textContent = times;
      var err = el.querySelector('.error');
      if (job.error) { if (!err) { err = document.createElement('div'); err.className = 'error'; el.appendChild(err); } err.textContent = job.error; }
    });
    var log = document.querySelector('[data-job-log="' + job.id + '"]');
    if (log) { var text = job.lines.join('\n') + '\n'; if (log.textContent !== text) { log.textContent = text; log.scrollTop = log.scrollHeight; } }
  }
  var active = document.getElementById('active-jobs');
  var page = document.querySelector('[data-job-log]');
  var list = document.getElementById('jobs-list');
  var wasRunning = null;
  function tick() {
    fetch('/api/jobs').then(function (r) { return r.json(); }).then(function (data) {
      var running = data.jobs.filter(function (j) { return j.state === 'queued' || j.state === 'running'; }).length;
      if (active) active.innerHTML = '<a href="/jobs">' + (running ? running + ' job' + (running === 1 ? '' : 's') + ' running' : 'idle') + '</a>';
      data.jobs.forEach(render);
      // A page that shows results of a job (result JSON, tables) reloads once
      // the job it shows has ended, so the numbers on it are current.
      if (page) {
        var id = page.getAttribute('data-job-log');
        var job = data.jobs.filter(function (j) { return String(j.id) === id; })[0];
        var isRunning = job && (job.state === 'queued' || job.state === 'running');
        if (wasRunning && !isRunning) { location.reload(); return; }
        wasRunning = isRunning;
      }
      if (list && data.jobs.length !== list.querySelectorAll('.job').length) { location.reload(); return; }
      setTimeout(tick, running ? 1000 : 5000);
    }).catch(function () { setTimeout(tick, 5000); });
  }
  if (active || page || list) tick();
})();
