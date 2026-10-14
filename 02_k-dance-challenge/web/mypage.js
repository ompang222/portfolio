document.addEventListener('DOMContentLoaded', () => {
  // 예시 데이터: 실제로는 서버나 API에서 받아올 수 있습니다.
  const playerData = {
      playerName : "하츄핑",
      playerLevel : 15,
      playTime : "12시간 45분",
      highScore : "11,000점",
      ranking : "상위 1%",
      favoriteSongs: [
          "아픈건 딱 질색이니까",
          "모기송",
          "Supersonic"
      ]
  }

  // 데이터를 페이지에 적용
  document.getElementById('playerName').textContent = playerData.playerName;
  document.getElementById('playerLevel').textContent = playerData.playerLevel;
  document.getElementById('playTime').textContent = playerData.playTime;
  document.getElementById('highScore').textContent = playerData.highScore;
  document.getElementById('ranking').textContent = playerData.ranking;

  // 즐겨찾는 곡 목록 표시
  const songList = document.getElementById('favoriteSongs');
  songList.innerHTML = '';  // 기존 내용을 지우고 새로 추가
  playerData.favoriteSongs.forEach(song => {
      const li = document.createElement('li');
      li.textContent = song;
      songList.appendChild(li);
  });

  // 로그아웃 버튼에 이벤트 리스너 추가
  document.querySelector('.logout-button').addEventListener('click', () => {
    logout();
  });
});

// 로그아웃 기능
function logout() {
    window.location.href = 'login.html'; // 로그인 페이지로 리다이렉트
}
