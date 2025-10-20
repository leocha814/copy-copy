"""
거래 상태 관리 모듈

현재 포지션 상태, 진입가, 진입 시간 등을 JSON 파일로 저장/로드하여
프로그램 재시작 시에도 상태를 유지합니다.
"""

import json
import os
import time
from typing import Dict, Optional, Any
from datetime import datetime
from src.logger import logger

class StateManager:
    """거래 상태 관리 클래스"""
    
    def __init__(self, state_file: str = ".state/trade_state.json"):
        self.state_file = state_file
        self.state_dir = os.path.dirname(state_file)
        
        # 상태 디렉토리 생성
        if not os.path.exists(self.state_dir):
            os.makedirs(self.state_dir, exist_ok=True)
        
        # 기본 상태
        self.default_state = {
            "has_position": False,
            "market": None,
            "entry_price": 0.0,
            "entry_time": 0,
            "entry_volume": 0.0,
            "entry_order_id": None,
            "last_signal": "HOLD",
            "last_update": time.time(),
            "total_trades": 0,
            "total_profit": 0.0,
            "win_count": 0,
            "loss_count": 0
        }
    
    def load_state(self) -> Dict[str, Any]:
        """상태 파일에서 거래 상태 로드"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                
                # 기본값으로 누락된 키 보완
                for key, default_value in self.default_state.items():
                    if key not in state:
                        state[key] = default_value
                
                logger.info(f"State loaded from {self.state_file}")
                return state
            else:
                logger.info("No existing state file, starting with default state")
                return self.default_state.copy()
        
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            logger.info("Using default state")
            return self.default_state.copy()
    
    def save_state(self, state: Dict[str, Any]) -> bool:
        """거래 상태를 파일에 저장"""
        try:
            # 타임스탬프 업데이트
            state["last_update"] = time.time()
            
            # 임시 파일에 먼저 저장 후 원본으로 이동 (원자적 쓰기)
            temp_file = f"{self.state_file}.tmp"
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            
            # 원본 파일로 이동
            os.rename(temp_file, self.state_file)
            
            logger.debug(f"State saved to {self.state_file}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False
    
    def enter_position(self, state: Dict[str, Any], market: str, entry_price: float, 
                      volume: float, order_id: Optional[str] = None) -> Dict[str, Any]:
        """포지션 진입 상태 업데이트"""
        state.update({
            "has_position": True,
            "market": market,
            "entry_price": entry_price,
            "entry_time": time.time(),
            "entry_volume": volume,
            "entry_order_id": order_id,
            "last_signal": "BUY"
        })
        
        logger.info(f"Position entered: {market} at {entry_price:,.0f} KRW, volume: {volume}")
        return state
    
    def exit_position(self, state: Dict[str, Any], exit_price: float, 
                     exit_reason: str, order_id: Optional[str] = None) -> Dict[str, Any]:
        """포지션 청산 상태 업데이트"""
        if not state.get("has_position"):
            logger.warning("Trying to exit position when no position exists")
            return state
        
        # 수익률 계산
        entry_price = state.get("entry_price", 0)
        if entry_price > 0:
            profit_rate = (exit_price - entry_price) / entry_price
            profit_krw = profit_rate * entry_price * state.get("entry_volume", 0)
        else:
            profit_rate = 0
            profit_krw = 0
        
        # 통계 업데이트
        state["total_trades"] += 1
        state["total_profit"] += profit_krw
        
        if profit_rate > 0:
            state["win_count"] += 1
        else:
            state["loss_count"] += 1
        
        # 포지션 정보 초기화
        state.update({
            "has_position": False,
            "market": None,
            "entry_price": 0.0,
            "entry_time": 0,
            "entry_volume": 0.0,
            "entry_order_id": None,
            "last_signal": "SELL"
        })
        
        logger.info(f"Position exited: {exit_reason}, profit: {profit_rate*100:.2f}% ({profit_krw:,.0f} KRW)")
        return state
    
    def get_position_info(self, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """현재 포지션 정보 반환"""
        if not state.get("has_position"):
            return None
        
        return {
            "market": state.get("market"),
            "entry_price": state.get("entry_price"),
            "entry_time": state.get("entry_time"),
            "entry_volume": state.get("entry_volume"),
            "entry_order_id": state.get("entry_order_id"),
            "hold_time": time.time() - state.get("entry_time", 0)
        }
    
    def get_trading_stats(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """거래 통계 반환"""
        total_trades = state.get("total_trades", 0)
        win_count = state.get("win_count", 0)
        loss_count = state.get("loss_count", 0)
        
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        return {
            "total_trades": total_trades,
            "total_profit": state.get("total_profit", 0),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": win_rate,
            "last_update": state.get("last_update", 0)
        }
    
    def reset_state(self) -> Dict[str, Any]:
        """상태 초기화"""
        logger.info("Resetting trading state")
        return self.default_state.copy()
    
    def backup_state(self) -> bool:
        """현재 상태 백업"""
        try:
            if os.path.exists(self.state_file):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = f"{self.state_file}.backup_{timestamp}"
                
                with open(self.state_file, 'r') as src, open(backup_file, 'w') as dst:
                    dst.write(src.read())
                
                logger.info(f"State backed up to {backup_file}")
                return True
        
        except Exception as e:
            logger.error(f"Failed to backup state: {e}")
        
        return False

# 기본 인스턴스
default_state_manager = StateManager()