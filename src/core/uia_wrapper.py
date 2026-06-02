# -*- coding: utf-8 -*-
"""
微信 UIAutomation 封装器 — 支持 WeChat 4.1.x FindAll 绕过
"""
import json
from . import uiautomation as uia
from .exceptions import ControlNotFoundError
from ..config import SEARCH_TIMEOUT
from ..utils.logger import get_logger

logger = get_logger(__name__)

# comtypes 用于绕过 WeChat 4.1.x 的 GetChildren 屏蔽
_com_client = None
_com_element_cache: dict = {}


def _ensure_com_client():
    """Lazy-init comtypes IUIAutomation client (bypasses WeChat 4.1 GetChildren block)."""
    global _com_client
    if _com_client is not None:
        return _com_client
    import comtypes.client as cc
    import comtypes.gen.UIAutomationClient as UIA
    _com_client = cc.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=UIA.IUIAutomation,
    )
    return _com_client


def _com_find_element(hwnd: int, name: str = None, class_name: str = None,
                      control_type: int = None, automation_id: str = None):
    """
    Find a single element using comtypes FindAll(Subtree).
    This bypasses WeChat 4.1.x's GetChildren block.
    Returns (element, rect_dict) or (None, None).
    """
    client = _ensure_com_client()
    import comtypes.gen.UIAutomationClient as UIA
    
    try:
        root = client.ElementFromHandle(hwnd)
        condition = client.CreateTrueCondition()
        all_elems = root.FindAll(UIA.TreeScope_Subtree, condition)
        
        best = None
        best_score = -1
        
        for i in range(all_elems.Length):
            e = all_elems.GetElement(i)
            try:
                en = e.CurrentName or ""
                ec = e.CurrentClassName or ""
                ea = e.CurrentAutomationId or ""
                ect = e.CurrentControlType
            except Exception:
                continue
            
            score = 0
            if name and name in en:
                score += 3 if en == name else 1
            if class_name and class_name in ec:
                score += 2
            if automation_id and automation_id in ea:
                score += 2
            if control_type is not None and ect == control_type:
                score += 1
            
            if score > best_score:
                best_score = score
                best = e
                
                # Exact match on name → return immediately
                if en.strip() == name.strip() and score >= 3:
                    break
        
        if best is not None:
            try:
                br = best.CurrentBoundingRectangle
                rect = {"left": br.left, "top": br.top, "right": br.right,
                        "bottom": br.bottom, "width": br.right - br.left,
                        "height": br.bottom - br.top}
            except Exception:
                rect = {}
            key = json.dumps([hwnd, name, class_name, automation_id])
            _com_element_cache[key] = (best, rect)
            return best, rect
    except Exception as e:
        logger.debug(f"com FindAll bypass failed: {e}")
    
    return None, None


def _com_find_all(hwnd: int, name: str = None, class_name: str = None) -> list:
    """Find all matching elements using comtypes FindAll(Subtree)."""
    client = _ensure_com_client()
    import comtypes.gen.UIAutomationClient as UIA
    
    results = []
    try:
        root = client.ElementFromHandle(hwnd)
        condition = client.CreateTrueCondition()
        all_elems = root.FindAll(UIA.TreeScope_Subtree, condition)
        
        for i in range(all_elems.Length):
            e = all_elems.GetElement(i)
            try:
                en = e.CurrentName or ""
                ec = e.CurrentClassName or ""
            except Exception:
                continue
            
            match = True
            if name and name not in en:
                match = False
            if class_name and class_name not in ec:
                match = False
            if match:
                try:
                    br = e.CurrentBoundingRectangle
                    rect = {"left": br.left, "top": br.top, "right": br.right,
                            "bottom": br.bottom, "width": br.right - br.left,
                            "height": br.bottom - br.top}
                except Exception:
                    rect = {}
                results.append({"name": en, "class": ec, "rect": rect, "element": i})
    except Exception as e:
        logger.debug(f"com FindAll failed: {e}")
    
    return results


def get_wechat_version() -> str:
    """Detect WeChat version from installed exe."""
    import subprocess
    for p in [r"C:\Program Files\Tencent\Weixin\Weixin.exe",
              r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe"]:
        try:
            r = subprocess.run(
                ["powershell", "-c", f"(Get-Item '{p}').VersionInfo.ProductVersion"],
                capture_output=True, text=True, timeout=5
            )
            v = r.stdout.strip()
            if v: return v
        except: pass
    return "unknown"


class UIAWrapper:
    """UIAutomation 操作封装器 — WeChat 4.1.x 兼容"""

    def __init__(self, hwnd: int = None):
        self._root: uia.WindowControl = None
        self._hwnd: int = 0
        self._wechat_ver: str = ""
        self._use_findall_bypass: bool = False
        if hwnd:
            self.bind(hwnd)

    def bind(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self._root = uia.ControlFromHandle(hwnd)
        if not self._root:
            raise ControlNotFoundError(f"无法从句柄 {hwnd} 获取 UIAutomation 控件")
        # Auto-detect if FindAll bypass is needed
        ver = get_wechat_version()
        self._wechat_ver = ver
        try:
            major = int(ver.split(".")[0]) if ver and ver[0].isdigit() else 0
            self._use_findall_bypass = (major >= 4)
        except:
            self._use_findall_bypass = False
        logger.debug(f"已绑定窗口: {self._root.Name} | WeChat {ver} | FindAll={'ON' if self._use_findall_bypass else 'OFF'}")

    @property
    def root(self) -> uia.WindowControl:
        return self._root

    def find_control(self, control_type: str = None, name: str = None,
                     class_name: str = None, automation_id: str = None,
                     timeout: float = None) -> uia.Control:
        """查找控件。WeChat 4.x 自动使用 FindAll 绕过。"""
        timeout = timeout or SEARCH_TIMEOUT

        # Strategy 1: comtypes FindAll bypass (WeChat 4.x)
        if self._use_findall_bypass and self._hwnd:
            try:
                elem, _ = _com_find_element(self._hwnd, name=name,
                                            class_name=class_name,
                                            automation_id=automation_id)
                if elem is not None and name and name in (elem.CurrentName or ""):
                    logger.debug(f"FindAll: found '{name}'")
                    return _ComControlProxy(elem, self._hwnd)
            except Exception as e:
                logger.debug(f"FindAll fallback: {e}")

        # Strategy 2: Standard uiautomation (WeChat 3.x and others)
        kwargs = {'searchDepth': 10}
        if name: kwargs['Name'] = name
        if class_name: kwargs['ClassName'] = class_name
        if automation_id: kwargs['AutomationId'] = automation_id

        ctrl_type = control_type or 'Control'
        getter = getattr(self._root, f'{ctrl_type}Control', None)
        if not getter: getter = self._root.Control

        ctrl = getter(**kwargs)
        if ctrl.Exists(maxSearchSeconds=timeout):
            return ctrl

        raise ControlNotFoundError(
            f"控件未找到: type={control_type}, name={name}, "
            f"class={class_name}, id={automation_id}"
        )

    def find_all_controls(self, control_type: str = None, **kwargs) -> list:
        """查找所有匹配控件。"""
        if self._use_findall_bypass and self._hwnd:
            return _com_find_all(self._hwnd, **kwargs)
        getter = getattr(self._root, f'{control_type}Control', self._root.Control)
        ctrl = getter(searchDepth=10, **kwargs)
        return ctrl.GetChildren() if ctrl.Exists() else []

    def find_chat_input(self) -> object:
        """Find the chat input field (mmui::ChatInputField) — WeChat 4.x specific."""
        if self._use_findall_bypass and self._hwnd:
            client = _ensure_com_client()
            import comtypes.gen.UIAutomationClient as UIA
            root = client.ElementFromHandle(self._hwnd)
            all_e = root.FindAll(UIA.TreeScope_Subtree, client.CreateTrueCondition())
            for i in range(all_e.Length):
                e = all_e.GetElement(i)
                if e.CurrentClassName == "mmui::ChatInputField":
                    return _ComControlProxy(e, self._hwnd)
        return self.find_control(class_name="mmui::ChatInputField")

    def find_send_button(self) -> object:
        """Find the send button (mmui::XOutlineButton name=发送)."""
        if self._use_findall_bypass and self._hwnd:
            client = _ensure_com_client()
            import comtypes.gen.UIAutomationClient as UIA
            root = client.ElementFromHandle(self._hwnd)
            all_e = root.FindAll(UIA.TreeScope_Subtree, client.CreateTrueCondition())
            for i in range(all_e.Length):
                e = all_e.GetElement(i)
                if e.CurrentName == "发送" and e.CurrentClassName == "mmui::XOutlineButton":
                    return _ComControlProxy(e, self._hwnd)
        return self.find_control(name="发送", class_name="mmui::XOutlineButton")

    def find_by_class_name(self, class_name: str, position: str = "any") -> object:
        """Find element by class name, optionally filtered by position (top/bottom/any)."""
        if self._use_findall_bypass and self._hwnd:
            client = _ensure_com_client()
            import comtypes.gen.UIAutomationClient as UIA
            root = client.ElementFromHandle(self._hwnd)
            all_e = root.FindAll(UIA.TreeScope_Subtree, client.CreateTrueCondition())
            candidates = []
            for i in range(all_e.Length):
                e = all_e.GetElement(i)
                if e.CurrentClassName == class_name:
                    try:
                        br = e.CurrentBoundingRectangle
                        candidates.append((br.top, e))
                    except:
                        pass
            if not candidates:
                return None
            if position == "bottom":
                candidates.sort(key=lambda x: -x[0])
            elif position == "top":
                candidates.sort(key=lambda x: x[0])
            return _ComControlProxy(candidates[0][1], self._hwnd)
        return self.find_control(class_name=class_name)

    def click(self, control) -> bool:
        """点击控件（支持 comtypes proxy 和 uiautomation Control）。"""
        try:
            if isinstance(control, _ComControlProxy):
                control.click()
            else:
                control.Click()
            logger.debug(f"已点击控件")
            return True
        except Exception as e:
            logger.error(f"点击控件失败: {e}")
            return False

    def send_keys(self, control, text: str) -> bool:
        """向控件发送按键。"""
        try:
            if isinstance(control, _ComControlProxy):
                control.send_keys(text)
            else:
                control.SendKeys(text)
            logger.debug(f"已发送按键: {text[:20]}...")
            return True
        except Exception as e:
            logger.error(f"发送按键失败: {e}")
            return False

    def get_rect(self, control) -> dict:
        """获取控件边界矩形。"""
        if isinstance(control, _ComControlProxy):
            return control.rect
        try:
            br = control.BoundingRectangle
            return {"left": br.left, "top": br.top, "right": br.right,
                    "bottom": br.bottom, "width": br.width(), "height": br.height()}
        except:
            return {}


class _ComControlProxy:
    """Proxy object that wraps a comtypes IUIAutomationElement with uiautomation-compatible API."""

    def __init__(self, elem, hwnd: int):
        self._elem = elem
        self._hwnd = hwnd
        self.Name = elem.CurrentName or ""
        self.ClassName = elem.CurrentClassName or ""
        self.AutomationId = elem.CurrentAutomationId or ""
        self.ControlType = elem.CurrentControlType
        self.ControlTypeName = ""  # filled later if needed
        try:
            br = elem.CurrentBoundingRectangle
            self.BoundingRectangle = type("Rect", (), {
                "left": br.left, "top": br.top, "right": br.right, "bottom": br.bottom,
                "width": lambda: br.right - br.left, "height": lambda: br.bottom - br.top
            })()
        except:
            self.BoundingRectangle = None

    @property
    def rect(self) -> dict:
        try:
            br = self._elem.CurrentBoundingRectangle
            return {"left": br.left, "top": br.top, "right": br.right,
                    "bottom": br.bottom, "width": br.right - br.left,
                    "height": br.bottom - br.top}
        except:
            return {}

    # --- PascalCase aliases (uiautomation compatibility) ---

    def Click(self, simulateMove: bool = False):
        """Click via InvokePattern or mouse fallback (compatible with uiautomation)."""
        return self.click(simulateMove)

    def DoubleClick(self, simulateMove: bool = False):
        """Double-click."""
        self.click(simulateMove)
        import time; time.sleep(0.1)
        self.click(simulateMove)

    def SendKeys(self, text: str):
        """Send text via ValuePattern or clipboard (compatible with uiautomation)."""
        return self.send_keys(text)

    def SetFocus(self):
        try:
            self._elem.SetFocus()
        except:
            pass

    def Exists(self, maxSearchSeconds: float = 0) -> bool:
        return True  # Already resolved by FindAll

    def GetChildren(self):
        return []  # Can't traverse; use FindAll for full tree

    # --- Internal implementations ---

    def click(self, simulateMove: bool = False):
        """Click via InvokePattern or mouse fallback."""
        import comtypes.gen.UIAutomationClient as UIA
        import time, win32api, win32con
        try:
            invoke = self._elem.GetCurrentPattern(UIA.UIA_InvokePatternId)
            invoke.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
            return
        except Exception:
            pass
        # Fallback: mouse click at center
        try:
            br = self._elem.CurrentBoundingRectangle
            cx = (br.left + br.right) // 2
            cy = (br.top + br.bottom) // 2
            win32api.SetCursorPos((cx, cy))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception as e:
            raise RuntimeError(f"Click failed: {e}")

    def send_keys(self, text: str):
        """Send text via ValuePattern.SetValue or clipboard paste."""
        import comtypes.gen.UIAutomationClient as UIA
        import time, pyperclip, win32api, win32con
        try:
            vp = self._elem.GetCurrentPattern(UIA.UIA_ValuePatternId)
            vp.QueryInterface(UIA.IUIAutomationValuePattern).SetValue(text)
            return
        except Exception:
            pass
        # Fallback: focus + clipboard paste
        try:
            self._elem.SetFocus()
            time.sleep(0.1)
            pyperclip.copy(text)
        except:
            pass
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x56, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x56, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
