export function connectWorkbench() {
  return new Promise((resolve, reject) => {
    const transport = window.qt?.webChannelTransport
    if (!transport || !window.QWebChannel) {
      reject(new Error('当前页面没有连接桌面程序。请从 ArknightsUnpacker 打开工作台。'))
      return
    }
    const timeout = window.setTimeout(() => {
      reject(new Error('连接桌面程序超时。请重新打开工作台。'))
    }, 8000)
    new window.QWebChannel(transport, ({ objects }) => {
      window.clearTimeout(timeout)
      if (objects.workbench) {
        resolve(objects.workbench)
      } else {
        reject(new Error('桌面程序未提供资源访问接口。'))
      }
    })
  })
}

export function invoke(bridge, action, payload = {}) {
  return new Promise((resolve, reject) => {
    bridge.invoke(action, JSON.stringify(payload), (reply) => {
      try {
        const result = JSON.parse(reply)
        if (!result.ok) {
          throw new Error(result.error || '操作失败')
        }
        resolve(result.data)
      } catch (error) {
        reject(error)
      }
    })
  })
}
