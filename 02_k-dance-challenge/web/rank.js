const rankings = {
  kpop: [
    { rank: 1, username: '하츄핑', score: 9800 },
    { rank: 2, username: '티니핑', score: 9500 },
    { rank: 3, username: '바로핑', score: 9200 },
    { rank: 4, username: '부끄핑', score: 8700 },
    { rank: 5, username: '깜빡핑', score: 7500 },
    { rank: 6, username: '아이핑', score: 7000 },
    { rank: 7, username: '누리핑', score: 6700 },
    { rank: 8, username: '라라핑', score: 6500 },
    { rank: 9, username: '차차핑', score: 6200 },
    { rank: 10, username: '보라핑', score: 6000 }
  ],
  challenge: [
    { rank: 1, username: '차차핑', score: 10000 },
    { rank: 2, username: '하츄핑', score: 9900 },
    { rank: 3, username: '라라핑', score: 9700 },
    { rank: 4, username: '해핑', score: 9600 },
    { rank: 5, username: '띠용핑', score: 9400 },
    { rank: 6, username: '주르핑', score: 9200 },
    { rank: 7, username: '말랑핑', score: 9000 },
    { rank: 8, username: '미미핑', score: 8800 },
    { rank: 9, username: '딩동핑', score: 8600 },
    { rank: 10, username: '콩콩핑', score: 8400 }
  ],
  all: [
    { rank: 1, username: '하츄핑', score: 11000 },
    { rank: 2, username: '해핑', score: 10500 },
    { rank: 3, username: '아이핑', score: 10200 },
    { rank: 4, username: '차나핑', score: 9800 },
    { rank: 5, username: '따라핑', score: 9700 },
    { rank: 6, username: '나르핑', score: 9600 },
    { rank: 7, username: '주르핑', score: 9500 },
    { rank: 8, username: '지니핑', score: 9400 },
    { rank: 9, username: '라라핑', score: 9300 },
    { rank: 10, username: '보니핑', score: 9200 }
  ]
};

function showRanking(category) {
  const tbody = document.getElementById('ranking-body');
  tbody.innerHTML = ''; // 기존 내용을 지우고

  rankings[category].forEach(player => {
    let crownImg = '';

    // 순위에 따라 메달 이미지를 선택
    if (player.rank === 1) {
      crownImg = '<img src="../img/goldmedal.png" alt="금메달" class="medal-icon">'; // 금메달
    } else if (player.rank === 2) {
      crownImg = '<img src="../img/silvermedal.png" alt="은메달" class="medal-icon">'; // 은메달
    } else if (player.rank === 3) {
      crownImg = '<img src="../img/bronzemedal.png" alt="동메달" class="medal-icon">'; // 동메달
    }

    const row = `
      <tr>
        <td>
          <div class="rank-container">
            ${crownImg}
            <span class="rank-number">${player.rank}</span>
          </div>
        </td>
        <td>${player.username}</td>
        <td class="score">${player.score}</td>
      </tr>`;
    tbody.innerHTML += row;
  });
}

// 초기 로딩 시 기본 K-pop Shots 랭킹 보여주기
document.addEventListener('DOMContentLoaded', function() {
  showRanking('kpop');
});
