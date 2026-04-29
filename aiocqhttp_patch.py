import os
import shutil
from datetime import datetime
from astrbot.api.all import logger

def patch_aiocqhttp(a=True):
    try:
        # 3. 定位 aiocqhttp 模块路径
        import aiocqhttp
        module_dir = os.path.dirname(aiocqhttp.__file__)
        target_file = os.path.join(module_dir, "__init__.py")
        if a and os.path.exists(target_file):
            if "ev['_raw_payload'] = dict(payload)" in open(target_file, "r", encoding="utf-8").read():
                return True

        # 1. 获取脚本所在目录
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # 2. 从当前脚本目录读取补丁文件
        patch_file = os.path.join(script_dir, "aiocqhttp__init__.txt")
        with open(patch_file, "r", encoding="utf-8") as f:
            patch_content = f.read()

        # 4. 自动备份源文件（带时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{target_file}.backup_{timestamp}"
        if os.path.exists(target_file):
            shutil.copy2(target_file, backup_file)
            logger.debug(f"✅ 源文件已备份: {backup_file}")

        # 5. 写入补丁
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(patch_content)

        logger.debug("✅ 补丁完成！")
        return False

    except ImportError as e:
        logger.debug("❌ 错误：未安装 aiocqhttp 模块\n"+str(e))
    except FileNotFoundError as e:
        logger.debug("❌ 错误：未找到补丁文件\n"+str(e))
    except PermissionError as e:
        logger.debug("❌ 错误：没有文件写入权限，请用管理员/root运行\n"+str(e))
    except Exception as e:
        logger.debug(f"❌ 补丁失败: {str(e)}")

if __name__ == "__main__":
    patch_aiocqhttp(False)