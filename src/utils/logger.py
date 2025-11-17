"""
로깅 유틸리티 모듈
데코레이터를 통한 로깅 기능 제공
"""

import logging
import functools
import traceback
from typing import Callable, Any, Optional
from datetime import datetime
import os

class Logger:
    """로깅 설정 및 관리 클래스"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logger()
            Logger._initialized = True
    
    def _setup_logger(self):
        """로거 설정"""
        # 로그 디렉토리 생성
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        # 로거 설정
        self.logger = logging.getLogger('PaperReview')
        self.logger.setLevel(logging.INFO)
        
        # 기존 핸들러 제거 (중복 방지)
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        # 포매터 설정
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 파일 핸들러
        file_handler = logging.FileHandler(
            os.path.join(log_dir, f'paper_review_{datetime.now().strftime("%Y%m%d")}.log'),
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        
        # 콘솔 핸들러
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_handler.setFormatter(formatter)
        
        # 핸들러 추가
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # 로그 레벨 설정
        self.logger.setLevel(logging.INFO)
    
    def get_logger(self):
        """로거 인스턴스 반환"""
        return self.logger

# 싱글톤 인스턴스 생성
logger_instance = Logger()
logger = logger_instance.get_logger()

def log_function_call(level: str = "INFO", log_args: bool = True, log_result: bool = True, 
                     log_exceptions: bool = True) -> Callable:
    """
    함수 호출을 로깅하는 데코레이터
    
    Args:
        level: 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
        log_args: 인자 로깅 여부
        log_result: 결과 로깅 여부
        log_exceptions: 예외 로깅 여부
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            log_level = getattr(logging, level.upper(), logging.INFO)
            
            # 함수 시작 로깅
            args_str = f"args={args}, kwargs={kwargs}" if log_args else ""
            logger.log(log_level, f"Starting {func.__name__} {args_str}")
            
            start_time = datetime.now()
            
            try:
                # 함수 실행
                result = func(*args, **kwargs)
                
                # 실행 시간 계산
                execution_time = (datetime.now() - start_time).total_seconds()
                
                # 결과 로깅
                if log_result:
                    result_str = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
                    logger.log(log_level, f"Completed {func.__name__} in {execution_time:.3f}s - Result: {result_str}")
                else:
                    logger.log(log_level, f"Completed {func.__name__} in {execution_time:.3f}s")
                
                return result
                
            except Exception as e:
                if log_exceptions:
                    logger.error(f"Error in {func.__name__}: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                raise
        
        return wrapper
    return decorator

def log_performance(threshold: float = 1.0) -> Callable:
    """
    성능 로깅 데코레이터
    
    Args:
        threshold: 경고할 실행 시간 임계값 (초)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                execution_time = (datetime.now() - start_time).total_seconds()
                
                if execution_time > threshold:
                    logger.warning(f"Slow function {func.__name__} took {execution_time:.3f}s (threshold: {threshold}s)")
                else:
                    logger.info(f"Function {func.__name__} executed in {execution_time:.3f}s")
                
                return result
                
            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"Function {func.__name__} failed after {execution_time:.3f}s: {str(e)}")
                raise
        
        return wrapper
    return decorator

def log_api_call(api_name: str = None) -> Callable:
    """
    API 호출 로깅 데코레이터
    
    Args:
        api_name: API 이름
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            api = api_name or func.__name__
            
            logger.info(f"API call started: {api}")
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                execution_time = (datetime.now() - start_time).total_seconds()
                
                logger.info(f"API call completed: {api} in {execution_time:.3f}s")
                return result
                
            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"API call failed: {api} after {execution_time:.3f}s - {str(e)}")
                raise
        
        return wrapper
    return decorator

def log_search_operation(source: str = None) -> Callable:
    """
    검색 작업 로깅 데코레이터
    
    Args:
        source: 검색 소스
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            search_source = source or func.__name__
            query = args[0] if args else kwargs.get('query', 'Unknown')
            max_results = kwargs.get('max_results', 'Unknown')
            
            logger.info(f"Search started - Source: {search_source}, Query: {query}, Max Results: {max_results}")
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                execution_time = (datetime.now() - start_time).total_seconds()
                
                result_count = len(result) if isinstance(result, list) else "Unknown"
                logger.info(f"Search completed - Source: {search_source}, Results: {result_count}, Time: {execution_time:.3f}s")
                
                return result
                
            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"Search failed - Source: {search_source}, Time: {execution_time:.3f}s, Error: {str(e)}")
                raise
        
        return wrapper
    return decorator

def log_data_processing(operation: str = None) -> Callable:
    """
    데이터 처리 로깅 데코레이터
    
    Args:
        operation: 처리 작업명
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            op_name = operation or func.__name__
            
            logger.info(f"Data processing started: {op_name}")
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                execution_time = (datetime.now() - start_time).total_seconds()
                
                logger.info(f"Data processing completed: {op_name} in {execution_time:.3f}s")
                return result
                
            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"Data processing failed: {op_name} after {execution_time:.3f}s - {str(e)}")
                raise
        
        return wrapper
    return decorator

def log_file_operation(operation: str = "file") -> Callable:
    """
    파일 작업 로깅 데코레이터
    
    Args:
        operation: 파일 작업명
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            filename = args[0] if args else kwargs.get('filename', 'Unknown')
            
            logger.info(f"File {operation} started: {filename}")
            start_time = datetime.now()
            
            try:
                result = func(*args, **kwargs)
                execution_time = (datetime.now() - start_time).total_seconds()
                
                logger.info(f"File {operation} completed: {filename} in {execution_time:.3f}s")
                return result
                
            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"File {operation} failed: {filename} after {execution_time:.3f}s - {str(e)}")
                raise
        
        return wrapper
    return decorator

# 편의를 위한 기본 데코레이터들
log_info = lambda func: log_function_call("INFO")(func)
log_debug = lambda func: log_function_call("DEBUG")(func)
log_warning = lambda func: log_function_call("WARNING")(func)
log_error = lambda func: log_function_call("ERROR")(func)

# 검색 관련 편의 데코레이터들
log_arxiv_search = lambda func: log_search_operation("arXiv")(func)
log_connected_papers_search = lambda func: log_search_operation("Connected Papers")(func)
log_google_scholar_search = lambda func: log_search_operation("Google Scholar")(func)
log_travily_search = lambda func: log_search_operation("Travily")(func)
