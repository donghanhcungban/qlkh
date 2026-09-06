import { Login } from './pages/Login';
import { ParentDashboard } from './pages/ParentDashboard';

// Điều hướng thật (react-router) sẽ được bổ sung khi tích hợp phiên đăng nhập
// thực tế; hiện tại App chỉ dựng entrypoint tối thiểu cho dev server.
export function App() {
  return (
    <div>
      <Login />
      <ParentDashboard />
    </div>
  );
}
