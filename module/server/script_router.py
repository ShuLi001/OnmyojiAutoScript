# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey
import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel, Field
from typing import Literal
from datetime import date, timedelta, timezone
from starlette.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime
from module.config.utils import convert_to_underscore

from module.logger import logger
from module.server.api_logger import ApiLoggingRoute, log_ws_event
from module.server.config_manager import (
    ConfigAlreadyExistsError,
    ConfigJsonError,
    ConfigManager,
    ConfigNameError,
    ConfigNotFoundError,
    ConfigTaskError,
    ConfigValidationError,
)
from module.server.main_manager import mm
from module.server.script_process import ScriptProcess, ScriptState

from tasks.Component.config_base import TimeDelta


script_app = APIRouter(route_class=ApiLoggingRoute)
from module.server.asset_capture_service import AssetCaptureService
asset_capture_service = AssetCaptureService(mm)


@script_app.get('/test')
async def script_test():
    return 'success'

@script_app.get('/script_menu')
async def script_menu():
    return mm.config_cache('template').gui_menu_list
# ----------------------------------   配置文件管理   ----------------------------------
@script_app.get('/config_list')
async def config_list():
    return mm.all_script_files()

@script_app.post('/config_copy')
async def config_copy(file: str, template: str = 'template'):
    mm.copy(file, template)
    return mm.all_script_files()

@script_app.get('/config_new_name')
async def config_new_name():
    return mm.generate_script_name()

@script_app.get('/config_all')
async def config_all():
    return mm.all_json_file()


@script_app.post('/config/import')
async def config_import(name: str = Form(...), file: UploadFile = File(...)):
    """
    导入脚本配置文件，上传文件名不会作为落盘名称。
    """
    try:
        raw = await file.read()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as e:
            raise ConfigJsonError(f'Config file must be UTF-8 JSON: {e}') from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ConfigJsonError(f'Config JSON parse failed: {e}') from e

        config_name = mm.import_config(name, data)
        mm.add_script_file(config_name)
        return {"name": config_name, "file": f"{config_name}.json"}
    except ConfigAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "fields": e.fields},
        )
    except (ConfigNameError, ConfigJsonError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.get('/config/export')
async def config_export(name: str):
    """
    导出脱敏后的脚本配置文件。
    """
    try:
        config_name, data = mm.load_config_for_export(name)
    except ConfigNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConfigJsonError as e:
        raise HTTPException(status_code=400, detail=str(e))

    redacted = ConfigManager.redact_config(data)
    content = json.dumps(redacted, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    filename = f"{config_name}.json"
    quoted_filename = quote(filename, safe='')
    fallback_filename = "config.json"
    return Response(
        content=content,
        media_type='application/json; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{fallback_filename}\"; filename*=UTF-8''{quoted_filename}",
            'Cache-Control': 'no-store',
        },
    )


@script_app.post('/config/task/import')
async def config_task_import(
    config_name: str = Form(...),
    task_name: str = Form(...),
    json_text: str | None = Form(None),
    file: UploadFile | None = File(None),
):
    """
    导入单个任务配置 JSON，内容必须是 {"task_key": {...}}。
    """
    try:
        file_content = await file.read() if file is not None else None
        data = mm.parse_task_json_source(json_text=json_text, file_content=file_content)
        config_name, task_key = mm.import_task_config(config_name, task_name, data)
        return {
            "config_name": config_name,
            "task_name": task_key,
            "file": f"{config_name}.json",
            "updated": True,
        }
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "fields": e.fields},
        )
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.get('/config/task/export')
async def config_task_export(config_name: str, task_name: str):
    """
    导出脱敏后的单个任务配置 JSON 文件。
    """
    try:
        config_name, task_key, data = mm.load_task_for_export(config_name, task_name)
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
    filename = f"{config_name}-{task_key}.json"
    quoted_filename = quote(filename, safe='')
    fallback_filename = "task.json"
    return Response(
        content=content,
        media_type='application/json; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{fallback_filename}\"; filename*=UTF-8''{quoted_filename}",
            'Cache-Control': 'no-store',
        },
    )


@script_app.get('/config/task/copy-json')
async def config_task_copy_json(config_name: str, task_name: str):
    """
    复制单个任务配置 JSON，返回未脱敏普通 JSON。
    """
    try:
        _, _, data = mm.load_task_for_transfer(config_name, task_name)
        return data
    except ConfigNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConfigNameError, ConfigJsonError, ConfigTaskError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@script_app.put('/config')
async def config_rename(old_name: str = '', new_name: str = ''):
    """
    update config name
    :param old_name: old config name
    :param new_name: new config name
    :return: True or False
    """
    if old_name == new_name or new_name == '':
        return False
    if old_name in mm.script_process:
        if mm.script_process[old_name].state != ScriptState.INACTIVE:
            mm.script_process[old_name].stop()
        del mm.script_process[old_name]
    if not mm.rename(old_name, new_name):
        raise HTTPException(status_code=400, detail='Rename failed')
    return True


@script_app.delete('/config')
async def config_delete(name: str = ''):
    """
    delete config file
    :param name: config name
    :return: True or False
    """
    if name == '' or name == 'template':
        raise HTTPException(status_code=400, detail='Delete failed')
    if name in mm.script_process:
        if mm.script_process[name].state != ScriptState.INACTIVE:
            mm.script_process[name].stop()
        del mm.script_process[name]
    if not mm.delete(name):
        raise HTTPException(status_code=400, detail='Delete failed')
    return True


@script_app.put('/config/task/copy')
async def task_copy(task_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_script_task(task_name, source_task)


@script_app.put('/config/task/group/copy')
async def task_group_copy(task_name: str, group_name: str, dest_config_name: str, source_config_name: str):
    if dest_config_name not in mm.script_process or source_config_name not in mm.script_process:
        return False
    source_task = getattr(mm.config_cache(source_config_name).model, convert_to_underscore(task_name), None)
    if source_task is None:
        return False
    return mm.config_cache(dest_config_name).model.copy_task_group(task_name, group_name, source_task)


# ---------------------------------   脚本实例管理   ----------------------------------
@script_app.get('/{script_name}/start')
async def script_start(script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    await mm.script_process[script_name].start()
    return

@script_app.get('/{script_name}/stop')
async def script_stop(script_name: str):
    asset_capture_service.cancel(script_name)
    if script_name not in mm.script_process:
        logger.warning(f'[{script_name}] script process does not exist')
        return
    await mm.script_process[script_name].stop()
    return


@script_app.get('/{script_name}/asset_snapshot')
async def script_asset_snapshot(script_name: str, response: Response,
                                compare: Literal['previous', 'seven_days'] = 'previous'):
    """Return the latest completed asset snapshot for an OAS profile."""
    from tasks.AssetSnapshot.statistics import latest_payload
    response.headers['Cache-Control'] = 'no-store'
    def read():
        store = asset_store(script_name)
        store.load()
        from tasks.AssetSnapshot.repository import STATISTICS_TZ
        today = datetime.now(STATISTICS_TZ).date()
        since = datetime.combine(today - timedelta(days=7), datetime.min.time(), tzinfo=STATISTICS_TZ)
        documents = store.repository.documents(since=since, include_latest=True)
        result = latest_payload(documents, store.repository.identity_id, compare)
        from tasks.AssetSnapshot.capture import CaptureQueue
        result['capture'] = CaptureQueue(store.repository).get()
        return result
    return await run_in_threadpool(read)


def asset_store(script_name):
    from tasks.AssetSnapshot.capture import store_for
    if script_name not in mm.all_script_files():
        raise HTTPException(status_code=404, detail='配置不存在')
    return store_for(mm.config_cache(script_name))


@script_app.get('/{script_name}/asset_snapshot/history')
async def script_asset_history(script_name: str, response: Response, asset: str,
                               days: int = Query(7, ge=1, le=31),
                               as_of_snapshot_id: int | None = Query(None, ge=1), report_date: date | None = None):
    from tasks.AssetSnapshot.statistics import history
    from tasks.AssetSnapshot.repository import STATISTICS_TZ
    response.headers['Cache-Control'] = 'no-store'
    def read():
        store = asset_store(script_name)
        if asset not in store.variables:
            raise HTTPException(status_code=422, detail='未知资产')
        store.load()
        end = report_date or datetime.now(STATISTICS_TZ).date()
        since = datetime.combine(end - timedelta(days=days), datetime.min.time(), tzinfo=STATISTICS_TZ)
        try:
            documents = store.repository.documents(as_of_snapshot_id, since)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error))
        result = history(documents, asset, end.isoformat(), days)
        if as_of_snapshot_id:
            result['window']['asOfSnapshotId'] = as_of_snapshot_id
        return result
    return await run_in_threadpool(read)


class AssetCaptureBody(BaseModel):
    idempotencyKey: str = Field(min_length=8, max_length=128)


@script_app.post('/{script_name}/asset_snapshot/captures', status_code=202)
async def script_asset_capture(script_name: str, body: AssetCaptureBody, response: Response):
    from tasks.AssetSnapshot.capture import CaptureQueue
    response.headers['Cache-Control'] = 'no-store'
    def submit():
        try:
            return CaptureQueue(asset_store(script_name).repository).submit(body.idempotencyKey)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error))
    result = await run_in_threadpool(submit)
    result['statusUrl'] = f'/{quote(script_name)}/asset_snapshot/captures/{result["requestId"]}'
    return result


@script_app.get('/{script_name}/asset_snapshot/captures/{request_id}')
async def script_asset_capture_status(script_name: str, request_id: str, response: Response):
    from tasks.AssetSnapshot.capture import CaptureQueue
    response.headers['Cache-Control'] = 'no-store'
    result = await run_in_threadpool(lambda: CaptureQueue(asset_store(script_name).repository).get(request_id))
    if result is None:
        raise HTTPException(status_code=404, detail='采集请求不存在')
    return result

@script_app.get('/{script_name}/{task}/args')
async def script_task(script_name: str, task: str):
    return mm.config_cache(script_name).model.script_task(task)

@script_app.put('/{script_name}/{task}/{group}/{argument}/value')
async def script_task(script_name: str, task: str, group: str, argument: str, types: str, value):
    try:
        match types:
            case 'integer':
                value = int(value)
            case 'number':
                value = float(value)
            case 'boolean':
                if isinstance(value, str):
                    logger.warning(f'[{script_name}] script argument {argument} value is string, try to convert to bool')
                    if value.lower() in ['true', '1']:
                        value = True
                    elif value.lower() in ['false', '0']:
                        value = False
                value = bool(value)
            case 'string':
                pass
            case 'date_time':
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            case 'time_delta':
                # strptime 是个好东西，但是不能解析00的天数
                day = int(value[1])
                date_time = datetime.strptime(value[3:], '%H:%M:%S')
                value = TimeDelta(days=day, hours=date_time.hour, minutes=date_time.minute, seconds=date_time.second)
            case 'time':
                value = datetime.strptime(value, '%H:%M:%S').time()
            case _: pass
    except Exception as e:
        # 类型不正确
        raise HTTPException(status_code=400, detail=f'Argument type error: {e}')
    model = mm.config_cache(script_name).model
    if task.lower() == 'script' and group == 'desktop' and argument == 'launch_instance' and value is True:
        from filelock import Timeout
        from module.config.utils import configured_device_id
        from tasks.AssetSnapshot.capture import device_lock

        def launch():
            try:
                with device_lock(configured_device_id(model)).acquire(timeout=0):
                    return model.script_set_arg(task, group, argument, value)
            except Timeout:
                logger.warning(f'[{script_name}] 设备正在被脚本使用，跳过手动启动')
                return False

        return await run_in_threadpool(launch)
    return model.script_set_arg(task, group, argument, value)


@script_app.get('/{script_name}/{task}/next_run_preview')
async def preview_next_run(script_name: str, task: str):
    if script_name not in mm.all_script_files():
        raise HTTPException(status_code=404, detail='Config not found')
    next_run = mm.config_cache(script_name).preview_task_next_run(task)
    return next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run is not None else None


@script_app.put('/{script_name}/{task}/sync_next_run')
async def sync_next_run(script_name: str, task: str, target_dt: str):
    if script_name not in mm.script_process:
        return False
    config = mm.config_cache(script_name)
    target = datetime.strptime(target_dt, '%Y-%m-%d %H:%M:%S') if target_dt else None
    config.task_delay(task=task, success=True, target=target)
    script_process = mm.script_process[script_name]
    config.get_next()
    await script_process.broadcast_state({"schedule": config.get_schedule_data()})
    return True


# --------------------------------------  SSE  --------------------------------------
@script_app.get('/{script_name}/state')
async def script_task_state(script_name: str):
    async def state_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: Hello, SSE!\n\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(state_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

@script_app.get('/{script_name}/log')
async def script_task_log(script_name: str):
    async def log_generate_events():
        while True:
            # 生成 SSE 事件数据
            event_data = "data: log\n"
            yield event_data

            # 模拟异步操作，可以替换为您的实际处理逻辑
            await asyncio.sleep(1)

    response = StreamingResponse(log_generate_events(), media_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response

# -------------------------------------- websocket --------------------------------------

@script_app.websocket("/ws/{script_name}")
async def websocket_endpoint(websocket: WebSocket, script_name: str):
    if script_name not in mm.script_process:
        mm.script_process[script_name] = ScriptProcess(script_name)
    script_process = mm.script_process[script_name]
    await script_process.connect(websocket)
    log_ws_event(f"ws[{script_name}] connected")

    try:
        await script_process.send_json(websocket, {"state": script_process.state})
        log_ws_event(f"ws[{script_name}] connect state: {script_process.state}")
        config = mm.config_cache(script_name)
        config.get_next()
        schedule_data = config.get_schedule_data()
        await script_process.send_json(websocket, {"schedule": schedule_data})
        log_ws_event(f"ws[{script_name}] connect response: {schedule_data}")
        while True:
            # 初次进入，广播state schedule
            data = await websocket.receive_text()
            log_ws_event(f"ws[{script_name}] msg: {data}")
            if data == 'get_state':
                await script_process.broadcast_state({"state": script_process.state})
                log_ws_event(f"ws[{script_name}] response: {script_process.state}")
            elif data == 'get_schedule':
                config = mm.config_cache(script_name)
                config.get_next()
                schedule_data = config.get_schedule_data()
                await script_process.broadcast_state({"schedule": schedule_data})
                log_ws_event(f"ws[{script_name}] response: {schedule_data}")
            elif data == 'start':
                await script_process.start()
            elif data == 'stop':
                await script_process.stop()

    except WebSocketDisconnect:
        log_ws_event(f"ws[{script_name}] disconnect", level="warning")
        await script_process.disconnect(websocket)
    except Exception as e:
        log_ws_event(f"ws[{script_name}] error: {type(e).__name__}: {e}", level="error")
        logger.exception(f'[{script_name}] websocket error: {e}')
        await script_process.disconnect(websocket)
