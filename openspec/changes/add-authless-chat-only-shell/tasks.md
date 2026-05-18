## 1. Route narrowing

- [x] 1.1 Redirect authless mode to `/chat` instead of `/dashboard`
- [x] 1.2 Prevent authless mode from rendering dashboard and admin pages

## 2. Desktop and mobile shell narrowing

- [x] 2.1 Reduce the desktop sidebar to chat-only navigation in authless mode
- [x] 2.2 Remove mobile settings/admin navigation in authless mode
- [x] 2.3 Simplify the mobile top bar so authless mode no longer shows account controls

## 3. Chat behavior narrowing

- [x] 3.1 Stop treating authless mode as an admin-wide session browser on the chat page
- [x] 3.2 Keep only conversation history and chat interaction visible in the authless shell

## 4. Verification

- [x] 4.1 Build the frontend and fix any routing or asset regressions
- [x] 4.2 Mark the spec tasks complete after verification
