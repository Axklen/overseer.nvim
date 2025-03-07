local task_list = require("overseer.task_list")
return {
  desc = "Ensure that this task does not have any duplicates",
  -- Doesn't make sense for user to add this using a form.
  editable = false,
  params = {
    replace = {
      desc = "If a prior task exists, replace it. When false, will restart the existing task and dispose the current task",
      long_desc = "Note that when this is false a new task that is created will restart the existing one and _dispose itself_. This can lead to unexpected behavior if you are creating a task and then trying to use that reference (to run actions on it, use it as a dependency, etc)",
      type = "boolean",
      default = true,
    },
    restart_interrupts = {
      desc = "When replace = false, should restarting the existing task interrupt it",
      type = "boolean",
      default = true,
    },
  },
  constructor = function(params)
    return {
      on_pre_start = function(_, task)
        local tasks = task_list.list_tasks()
        for _, t in ipairs(tasks) do
          if t.name == task.name and t ~= task then
            if params.replace then
              t:dispose(true)
            else
              task:dispose(true)
              t:restart(params.restart_interrupts)
              return false
            end
          end
        end
      end,
    }
  end,
}
