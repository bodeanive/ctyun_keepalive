# -*- coding: utf-8 -*-
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, ElementNotInteractableException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from pyvirtualdisplay import Display
import time
import logging # 导入标准的 logging 模块
import sys
import os
import json
import requests
import threading
from queue import Queue, Empty # 为超时异常添加了 Empty

# --- 自定义模块导入和日志记录器初始化 ---
# 尝试导入用户自定义模块
try:
    import logger # 导入你自定义的 logger 模块
except ImportError:
    logger = None # 标记 logger 模块未找到

try:
    import my_captcha
except ImportError:
    my_captcha = None # 标记 my_captcha 模块未找到

try:
    import webthread
except ImportError:
    webthread = None # 标记 webthread 模块未找到


# 优先尝试使用你自定义的 logger.Logger
if logger and hasattr(logger, 'Logger'):
    try:
        __g_logger = logger.Logger(path="static/ctyun.txt", Flevel=logging.INFO)
        # 为了确认日志已正确配置到文件，可以在这里打印一条消息到控制台（可选）
        print("自定义日志记录器已配置，日志将尝试写入到 'static/ctyun.txt'")
    except Exception as e_logger_init:
        # 自定义 Logger 初始化失败
        print(f"警告: 初始化自定义 Logger 时发生错误: {e_logger_init}。将回退到标准控制台日志记录。")
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        __g_logger = logging.getLogger("ctyun_fallback_logger_custom_error")
else:
    # 如果 logger 模块未找到或没有 Logger 类
    if logger is None:
        print("警告: 自定义日志模块 'logger.py' 未找到。将回退到标准控制台日志记录。")
    else:
        print("警告: 自定义日志模块 'logger.py' 中未找到 'Logger' 类。将回退到标准控制台日志记录。")
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    __g_logger = logging.getLogger("ctyun_fallback_logger_no_custom")
# --- 日志记录器初始化结束 ---


def isNeedDisplay(bMustVirtualDisplay=1): # 使用你的原始逻辑
    if "linux" in sys.platform:
        if bMustVirtualDisplay:
            return 1 # PyVirtualDisplay
        else:
            return 2  # Headless Linux
    return 0 # 适用于其他操作系统 (例如 Windows) 或不需要虚拟显示的情况

def pushmsg(push_token, title, content):
    if not push_token:
        __g_logger.debug("推送 token 为空，跳过推送消息。")
        return ''
    url = f'https://iyuu.cn/{push_token}.send'
    params = {'text': title, 'desp': content}
    try:
        response = requests.get(url, params=params, timeout=10)
        __g_logger.info(f"推送消息已发送。标题: '{title}'. 响应: {response.text[:100]}")
        return response.text
    except requests.RequestException as e:
        __g_logger.error(f"推送消息失败: {e}")
        return str(e)

# 辅助函数，用于执行给定步骤的操作
def _execute_step_actions(driver, step_config, __g_logger_param): # 明确传递 logger
    __g_logger_param.info(f"正在执行步骤的操作: {step_config['name']}")
    for elem_details in step_config['elems']:
        locator_str = elem_details[0]
        find_by_method = elem_details[1]
        action_type = elem_details[2]
        action_param = elem_details[3]
        
        __g_logger_param.debug(f"尝试操作: {action_type} 于元素 '{locator_str}' (通过 {find_by_method})，参数 '{action_param}'")
        
        try:
            target_element = None
            if find_by_method == "active_element":
                target_element = driver.switch_to.active_element
                __g_logger_param.debug("目标为活动元素。")
            else:
                target_element = driver.find_element(find_by_method, locator_str)
                __g_logger_param.debug(f"元素 '{locator_str}' 已找到。")

            if action_type == 'send_keys':
                # 对于 active_element，不应该调用 .clear()
                if find_by_method != "active_element":
                    target_element.clear() # 只对非 active_element 执行 clear
                
                target_element.send_keys(action_param)
                __g_logger_param.debug(f"已发送文本 '{action_param}'。")
                
                if find_by_method == "active_element": 
                    target_element.send_keys(Keys.ENTER)
                    __g_logger_param.debug("已向活动元素发送 ENTER 键。")
            elif action_type == 'click':
                target_element.click()
                __g_logger_param.debug("已点击元素。")
                if isinstance(action_param, (str, int)) and str(action_param).isdigit() and int(action_param) > 0:
                    sleep_duration = int(action_param)
                    __g_logger_param.debug(f"点击后休眠 {sleep_duration} 秒。")
                    time.sleep(sleep_duration)
            
            # 如果没有明确的休眠，则添加一个小的默认延迟
            if not (action_type == 'click' and isinstance(action_param, (str, int)) and str(action_param).isdigit()):
                time.sleep(1) 

        except ElementNotInteractableException:
            #重复 忽略关闭窗口
            __g_logger_param.warn(f"在步骤 '{step_config['name']}' 中未找到元素: '{locator_str}' (通过 {find_by_method})")
            pass

        except NoSuchElementException:
            __g_logger_param.warn(f"在步骤 '{step_config['name']}' 中未找到元素: '{locator_str}' (通过 {find_by_method})")
            try:
                tips_obj = driver.find_element(By.CLASS_NAME, 'el-message__content')
                __g_logger_param.warn(f"检测到页面提示: {tips_obj.text}")
            except NoSuchElementException:
                pass
            return False
        except Exception as e: # 捕获更广泛的异常，包括 InvalidElementStateException
            __g_logger_param.error(f"在元素 '{locator_str}' 上执行操作 '{action_type}' 时出错: {type(e).__name__} - {e}")
            import traceback
            __g_logger_param.error(traceback.format_exc())
            return False
    return True


def keepalive_ctyun2(parms, url="https://pc.ctyun.cn/#/login"):
    # 使用全局的 __g_logger
    global __g_logger
    
    if hasattr(__g_logger, 'setModulename'):
        try:
            __g_logger.setModulename("keepalive_ctyun")
        except Exception as e_setmodule:
            __g_logger.warn(f"调用 setModulename 失败: {e_setmodule}")

    __g_logger.info(f"启动天翼云保活进程，账户: {parms.get('account')}")

    if parms is None:
        __g_logger.warning("参数对象 'parms' 为 None。")
        return -1

    base_ctyun_steps = [
        {"name": "登录输入", "elems": [
            ['account', By.CLASS_NAME, 'send_keys', '%ACCOUNT%'],
            ['password', By.CLASS_NAME, 'send_keys', '%CTPASSWORD%'],
            ['btn-submit', By.CLASS_NAME, 'click', '3']
        ]},
        {"name": "进入云主机", "elems": [
            ['desktop-main-entry', By.CLASS_NAME, 'click', '5']
        ]},
        {"name": "Windows登录", "elems": [
            ["close-ai", By.CLASS_NAME, "click", "3"],
            ['screenContainer', By.CLASS_NAME, 'click', '15'],
            ['winpassword', "active_element", 'send_keys', '%WINPASSWORD%']
        ]}
    ]

    ctyun_steps = json.loads(json.dumps(base_ctyun_steps))
    for step_conf in ctyun_steps:
        for elem_conf in step_conf['elems']:
            if elem_conf[3] == "%ACCOUNT%": elem_conf[3] = parms['account']
            elif elem_conf[3] == "%CTPASSWORD%": elem_conf[3] = parms['password']
            elif elem_conf[3] == "%WINPASSWORD%": elem_conf[3] = '999' + parms['password']
    
    browser_type = parms.get('browserType', 'edge').lower()
    if browser_type == 'edge':
        options = webdriver.EdgeOptions()
        options.use_chromium = True
    else:
        options = webdriver.ChromeOptions()

    display_mode = isNeedDisplay()
    display_obj = None # 用于 pyvirtualdisplay
    if display_mode == 1:
        try:
            display_obj = Display(visible=False, size=(1024, 768))
            display_obj.start()
            __g_logger.info("虚拟显示已启动。")
        except Exception as e_display:
            __g_logger.error(f"启动虚拟显示失败: {e_display}. 可能需要安装 xvfb 和 PyVirtualDisplay.")
            display_mode = 0 # 回退到非虚拟显示模式
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('blink-settings=imagesEnabled=false')
    elif display_mode == 2:
        __g_logger.info("正在配置 Headless Linux。")
        options.add_argument('--no-sandbox')
        options.add_argument('window-size=1280x800')
        options.add_argument('--disable-gpu')
        options.add_argument('--hide-scrollbars')
        options.add_argument('blink-settings=imagesEnabled=false')
        options.add_argument('--headless=new')
    else:
        __g_logger.info("正在配置标准 (非 headless/非虚拟) 显示。")
        options.add_argument('blink-settings=imagesEnabled=false')
        options.add_argument('--start-maximized')

    options.add_argument('--disable-extensions')
    options.add_argument('--log-level=3')
    options.add_argument("--disable-dev-shm-usage")

    listen_url_display = parms.get('listen_url', '')
    if not listen_url_display:
         listen_url_display = getDefaultUrl(port=parms.get('listenport', 8000))
    
    listen_url_for_push = listen_url_display
    if parms.get('listenport',0) > 0 and not listen_url_display.startswith('<a href'):
        listen_url_for_push = f'<a href="{listen_url_display}">点击输入(click to input)</a>'

    driver = None
    verifyCodeQueue = None
    web_thread_started = False

    try:
        if parms.get('listenport', 0) > 0:
            if webthread and hasattr(webthread, 'web_run'):
                verifyCodeQueue = Queue()
                webthread.web_run(verifyCodeQueue, port=parms['listenport'])
                web_thread_started = True
                __g_logger.info(f"验证码输入服务应在 {listen_url_display} 启动")
            else:
                __g_logger.warn("webthread 模块或 web_run 函数未找到，无法启动Web验证码服务。")


        __g_logger.info(f"尝试启动 {browser_type} webdriver...")
        browser_path = parms.get('browserPath', '')
        if browser_type == 'edge':
            if browser_path: options.binary_location = browser_path
            service = webdriver.EdgeService()
            driver = webdriver.Edge(service=service, options=options)
        else:
            if browser_path: options.binary_location = browser_path
            service = webdriver.ChromeService()
            driver = webdriver.Chrome(service=service, options=options)
        __g_logger.info("WebDriver 已成功启动。")
        
        driver.get(url)
        __g_logger.info(f"已导航到登录页面: {url}")
        time.sleep(3)

        step_1_config = ctyun_steps[0]
        __g_logger.info(f"开始步骤 1: {step_1_config['name']}")
        
        if driver.current_url.startswith(url):
            try:
                time.sleep(2)
                code_input_field = driver.find_element(By.CLASS_NAME, 'code')
                
                if code_input_field.is_displayed() and code_input_field.get_attribute('value') == '':
                    code_img = driver.find_element(By.CLASS_NAME, 'code-img')
                    __g_logger.warn("登录需要验证码！")
                    __g_logger.info(f"验证码图片 src: {code_img.get_attribute('src')}")
                    
                    if parms.get('push_token'):
                        pushmsg(parms['push_token'], '天翼云电脑保活需要验证码', listen_url_for_push)
                    
                    os.makedirs('static', exist_ok=True)
                    screenshot_path = 'static/ctyun_login_page.png'
                    captcha_img_path = 'static/verifyCode.png'
                    driver.get_screenshot_as_file(screenshot_path)
                    code_img.screenshot(captcha_img_path)
                    __g_logger.info(f"页面截图: {screenshot_path}, 验证码图片: {captcha_img_path}")

                    verify_code_str = None
                    if my_captcha and hasattr(my_captcha, 'captcha_pic') and parms.get('captcha_auto_solve', False):
                        try:
                            verify_code_str = my_captcha.captcha_pic(captcha_img_path)
                            if verify_code_str: __g_logger.info(f"验证码自动识别成功: {verify_code_str}")
                        except Exception as e_captcha_solve:
                             __g_logger.warn(f"自动识别验证码失败: {e_captcha_solve}")

                    if not verify_code_str and web_thread_started and verifyCodeQueue:
                        try:
                            __g_logger.info("通过 Web 界面等待验证码 (60秒超时)...")
                            verify_code_str = verifyCodeQueue.get(block=True, timeout=60)
                            __g_logger.info(f"收到验证码: {verify_code_str}")
                        except Empty: 
                            __g_logger.warn("从队列等待验证码超时。")
                        except Exception as e_q:
                             __g_logger.warn(f"从队列获取验证码时出错: {e_q}")
                    elif not verify_code_str:
                        verify_code_str = input("请输入验证码: ")
                    
                    if verify_code_str:
                        code_input_field.clear()
                        code_input_field.send_keys(verify_code_str)
                        time.sleep(1)
                    else:
                        err_msg = "未能获取验证码。正在中止登录。"
                        __g_logger.error(err_msg)
                        raise Exception(err_msg)
            except NoSuchElementException:
                __g_logger.info("登录页面未找到验证码字段，继续操作。")
            except Exception as e_captcha_handling:
                 __g_logger.error(f"处理验证码时出错: {e_captcha_handling}")
                 raise

        if not _execute_step_actions(driver, step_1_config, __g_logger):
            raise Exception(f"步骤 1 '{step_1_config['name']}' 失败。")

        desktoo_url = driver.current_url
        __g_logger.info(f"步骤 1 '{step_1_config['name']}' 完成。当前 URL: {driver.current_url}")
        time.sleep(5)

        step_2_config = ctyun_steps[1]
        __g_logger.info(f"开始步骤 2: {step_2_config['name']}")
        if not _execute_step_actions(driver, step_2_config, __g_logger):
            raise Exception(f"步骤 2 '{step_2_config['name']}' 失败。")
        __g_logger.info(f"步骤 2 '{step_2_config['name']}' 完成。当前 URL: {driver.current_url}")
        time.sleep(5) 

        step_3_config = ctyun_steps[2]
        __g_logger.info(f"开始步骤 3: {step_3_config['name']}")
        if not _execute_step_actions(driver, step_3_config, __g_logger):
            raise Exception(f"步骤 3 '{step_3_config['name']}' 失败。")
        __g_logger.info(f"步骤 3 '{step_3_config['name']}' 完成。当前 URL: {driver.current_url}")
        
        os.makedirs('static', exist_ok=True)
        driver.get_screenshot_as_file('static/ctyun_after_initial_steps.png')
        __g_logger.info("初始步骤 (1, 2, 3) 已成功完成。进入保活循环。")
        pushmsg(parms.get('push_token'), '天翼云电脑初始保活成功', f"登录成功，当前时间: {time.asctime()}")

        while True:
            wait_duration_seconds = 15 * 60
            __g_logger.info(f"等待 {wait_duration_seconds / 60:.0f} 分钟后重复步骤 2 和 3...")
            
            for t in range(0, wait_duration_seconds, 300):
                time.sleep(min(300, wait_duration_seconds - t))
                remaining_minutes = (wait_duration_seconds - (t + min(300, wait_duration_seconds - t))) / 60
                if remaining_minutes > 0:
                     __g_logger.debug(f"保活: 当前等待周期剩余 {remaining_minutes:.0f} 分钟。")
            
            __g_logger.info(f"重复步骤 2: {step_2_config['name']}")
            driver.get(desktoo_url)
            time.sleep(25)
            if not _execute_step_actions(driver, step_2_config, __g_logger):
                __g_logger.error(f"重复步骤 2 '{step_2_config['name']}' 失败。尝试重新登录。")
                pushmsg(parms.get('push_token'), '天翼云警告：步骤2执行失败', f"尝试重新登录，时间: {time.asctime()}")
                driver.get(url)
                time.sleep(3)
                '''
                '''
            __g_logger.info(f"重复步骤 3: {step_3_config['name']}")
            if not _execute_step_actions(driver, step_3_config, __g_logger):
                __g_logger.error(f"重复步骤 3 '{step_3_config['name']}' 失败。")
                pushmsg(parms.get('push_token'), '天翼云警告：步骤3执行失败', f"将会在下个周期重试，时间: {time.asctime()}")
            
            os.makedirs('static', exist_ok=True)
            screenshot_filename = f'static/ctyun_heartbeat_{time.strftime("%Y%m%d_%H%M%S")}.png'
            driver.get_screenshot_as_file(screenshot_filename)
            __g_logger.info(f"步骤 2 和 3 已重新执行。截图: {screenshot_filename}。当前 URL: {driver.current_url}")
            pushmsg(parms.get('push_token'), '天翼云电脑周期保活完成', f"步骤2和3已执行。截图: {screenshot_filename}，时间: {time.asctime()}")

    except KeyboardInterrupt:
        __g_logger.info("用户通过键盘中断 (KeyboardInterrupt) 终止进程。")
        if parms.get('push_token'): pushmsg(parms.get('push_token'), '天翼云电脑保活停止', f"用户手动停止，时间: {time.asctime()}")
    except Exception as e:
        import traceback
        __g_logger.error(f"keepalive_ctyun2 中发生未处理的错误: {e}")
        __g_logger.error(traceback.format_exc())
        if driver:
            os.makedirs('static', exist_ok=True)
            try:
                driver.get_screenshot_as_file('static/ctyun_critical_error.png')
                __g_logger.info("错误截图已保存到 static/ctyun_critical_error.png")
            except Exception as e_screenshot:
                __g_logger.error(f"保存错误截图失败: {e_screenshot}")
        if parms.get('push_token'): pushmsg(parms.get('push_token'), '天翼云电脑保活严重错误', f"错误: {e}, 时间: {time.asctime()}")
    finally:
        __g_logger.info("正在清理资源...")
        if driver:
            driver.quit()
            __g_logger.info("WebDriver 已退出。")
        
        if display_mode == 1 and display_obj and display_obj.is_started:
            try:
                display_obj.stop()
                __g_logger.info("虚拟显示已停止。")
            except Exception as e_display_stop:
                 __g_logger.error(f"停止虚拟显示失败: {e_display_stop}")
        
        __g_logger.info("保活进程已结束。")
    return 0
    
#获取输入验证码网页地址
# 参数：
#   protocal:http或https
#   port端口
#   iptype：local（局域网地址），internet（互联网地址）
def getDefaultUrl(protocal='http',port=8000,iptype='local'):
    ip=None
    if(iptype == 'local'):
        #局域网
        try:
            import socket
            host_name = socket.gethostname()
            ip = socket.gethostbyname(host_name)
        except:
            __g_logger.warn("Can not get local IP")
    else:
        #互联网    
        ip=requests.get('http://ip-api.com/csv/?fields=query', timeout=5).text
    #listen_url='<a href="http://'+ip.rstrip()+':8000/">click to input.</a>'
    listen_url=f'{protocal}://{ip}:{port}/'
    return listen_url


if __name__ == '__main__':
    parms = {
        'account': '', 'password': '',
        'browserType': 'edge', 'browserPath': '',
        'listenport': 8000, 'listen_url': '',
        'push_token': '',
        'captcha_auto_solve': False
    }

    # 确保 static 目录存在，用于日志和截图
    os.makedirs('static', exist_ok=True)

    try:
        with open(r"my.json", encoding='utf-8') as json_file:
            user_parms = json.load(json_file)
            parms.update(user_parms)
            __g_logger.info("已从 my.json 加载参数")
    except FileNotFoundError:
        __g_logger.warn("未找到 my.json 配置文件。将使用默认值和命令行参数。")
    except json.JSONDecodeError:
        __g_logger.warn("解码 my.json 时出错。请检查其格式。将使用默认值和命令行参数。")
    except Exception as e:
        __g_logger.warn(f"加载 my.json 时出错: {e}。将使用默认值和命令行参数。")

    if len(sys.argv) >= 3:
        parms['account'] = sys.argv[1]
        parms['password'] = sys.argv[2]
        if len(sys.argv) > 3: parms['browserType'] = sys.argv[3]
        if len(sys.argv) > 4 and sys.argv[4]: parms['browserPath'] = sys.argv[4]
        if len(sys.argv) > 5:
            try: parms['listenport'] = int(sys.argv[5])
            except ValueError: __g_logger.error(f"来自命令行的 listenport 无效: {sys.argv[5]}")
        if len(sys.argv) > 6: parms['push_token'] = sys.argv[6]
        # 示例: if len(sys.argv) > 7 and sys.argv[7].lower() == 'true': parms['captcha_auto_solve'] = True


    if not parms['account'] or not parms['password']:
        print('用法: python your_script_name.py <账户> <"密码"> [浏览器类型] [浏览器路径] [监听端口] [推送token]')
        # __g_logger 会在这里记录 (如果已配置)
        __g_logger.error("账户或密码未提供，脚本退出。")
        sys.exit(1)
    
    __g_logger.info(f"最终执行参数: {json.dumps(parms, indent=2, ensure_ascii=False)}")
            
    ret = keepalive_ctyun2(parms=parms)
    sys.exit(ret)
