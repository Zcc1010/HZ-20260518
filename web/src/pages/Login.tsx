import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import api from "../lib/api";
import { BRAND_ASSETS, BRAND_NAME } from "../lib/branding";
import { useAuthStore } from "../stores/authStore";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "../components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import { User, Lock, Languages } from "lucide-react";
import { LANGUAGE_OPTIONS, getLanguageLabel } from "../i18n/languages";

export default function Login() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) {
      toast.error(t("auth.fieldRequired"));
      return;
    }
    setLoading(true);
    try {
      const res = await api.post("/auth/login", { username, password });
      const { access_token, user } = res.data;
      setAuth(user, access_token);
      navigate("/dashboard");
    } catch {
      toast.error(t("auth.loginFailed"));
    } finally {
      setLoading(false);
    }
  };

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-sky-50 via-white to-blue-100 px-4">
      {/* 装饰性背景圆圈 */}
      <div className="absolute top-0 left-0 w-96 h-96 bg-sky-200/40 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2"></div>
      <div className="absolute bottom-0 right-0 w-96 h-96 bg-blue-200/40 rounded-full blur-3xl translate-x-1/2 translate-y-1/2"></div>
      
      {/* 语言切换按钮 */}
      <div className="absolute top-4 right-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="gap-2 backdrop-blur-sm bg-white/50 dark:bg-gray-900/50">
              <Languages className="h-4 w-4" />
              {getLanguageLabel(i18n.language)}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {LANGUAGE_OPTIONS.map(({ code, label }) => (
              <DropdownMenuItem key={code} onClick={() => changeLanguage(code)}>
                {label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Card className="w-full max-w-sm shadow-2xl backdrop-blur-sm bg-white/85 border-sky-200/70 animate-in fade-in zoom-in duration-500">
        <CardHeader className="text-center space-y-3 pb-4">
          <div className="flex justify-center">
            <div className="relative">
              <div className="absolute inset-0 bg-sky-300/30 rounded-2xl blur-xl animate-pulse"></div>
              <img 
                src={BRAND_ASSETS.icon} 
                alt={BRAND_NAME} 
                className="relative h-16 w-16 rounded-2xl shadow-lg ring-2 ring-sky-100" 
              />
            </div>
          </div>
          <div>
            <CardTitle className="brand-display brand-gradient-text text-2xl font-bold">
              {BRAND_NAME}
            </CardTitle>
            <CardDescription className="text-sm mt-1">{t("auth.login")}</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username" className="text-sm font-medium">
                {t("auth.username")}
              </Label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#4760ff]" />
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  className="pl-10 h-10 border-sky-200 focus-visible:ring-[#549dff] bg-gradient-to-r from-sky-50/80 to-white"
                  placeholder={t("auth.username")}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="password" className="text-sm font-medium">
                {t("auth.password")}
              </Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#4760ff]" />
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  className="pl-10 h-10 border-sky-200 focus-visible:ring-[#549dff] bg-gradient-to-r from-sky-50/80 to-white"
                  placeholder={t("auth.password")}
                />
              </div>
            </div>
            <Button 
              type="submit" 
              className="w-full h-10 mt-6 bg-gradient-to-r from-[#0dccff] via-[#4760ff] to-[#f760ff] text-white font-semibold shadow-xl shadow-blue-500/30 transition-all duration-300 hover:scale-[1.02]" 
              disabled={loading}
            >
              {loading ? t("common.loading") : t("auth.loginButton")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
