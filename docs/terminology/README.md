# Platform terminology

Use the terms from the project brief consistently:

- **Platform** is the entire Home Platform system.
- **Control Plane** coordinates configuration and Desired State.
- **Node** is a computer; a **Device** is physical hardware associated with it.
- **Service** provides a continuously available capability; a **Provider** is
  the Node currently offering it.
- **Route** chooses a Provider for a capability.
- **Automation**, **Run**, and **Stage** describe durable workflows.
- **Command** asks for an action; an **Event** states that something occurred.
- **Desired State**, **Actual State**, **Health**, **Telemetry**, and **Alert**
  retain their precise operational meanings.

Avoid calling ordinary Node software an “agent.” Reserve **AI Agent** for
autonomous AI behavior.
